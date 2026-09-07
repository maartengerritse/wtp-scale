#!/usr/bin/env python3
"""Look inside the running kiosk page.

Chromium is started with a DevTools port bound to localhost (see kiosk.sh),
which lets this ask the live page questions instead of guessing from the
outside. Standard library only -- it has to run on a bare Pi.

    pi/inspect.py                  video state: playhead, paused, stalled, errors
    pi/inspect.py view             which screen is showing, and which product
    pi/inspect.py 'JS expression'  anything else; the result is printed as JSON

Run it on the Pi, or from a Mac:
    ssh buynamics@raspberrypi.local ~/wtp-scale/pi/inspect.py
"""

import json
import os
import socket
import struct
import sys
import urllib.request

PORT = 9222

PRESETS = {
    "videos": """JSON.stringify([...document.querySelectorAll("video")].map(v => ({
        id: v.id, src: (v.currentSrc || "").split("/").pop(),
        t: +v.currentTime.toFixed(2), duration: v.duration ? +v.duration.toFixed(2) : null,
        paused: v.paused, ended: v.ended, loop: v.loop, readyState: v.readyState,
        error: v.error ? v.error.code : null })), null, 1)""",
    "view": """JSON.stringify({
        view: [...document.querySelectorAll(".view")].find(v => v.classList.contains("is-active")).id,
        product: (document.getElementById("product-name") || {}).textContent || null,
        readerWarning: !document.getElementById("reader-warning").hidden }, null, 1)""",
}


def evaluate(expression):
    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5))
    page = next(t for t in targets if t["type"] == "page")
    path = page["webSocketDebuggerUrl"].split(str(PORT), 1)[1]

    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {os.urandom(16).hex()[:22]}==\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)

    def send(text):
        data = text.encode()
        mask = os.urandom(4)
        if len(data) < 126:
            header = bytes([0x81, 0x80 | len(data)])
        else:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", len(data))
        s.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def read_exact(n):
        out = b""
        while len(out) < n:
            chunk = s.recv(n - len(out))
            if not chunk:
                raise ConnectionError("DevTools socket closed")
            out += chunk
        return out

    def receive():
        _, b2 = read_exact(2)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", read_exact(8))[0]
        return read_exact(length).decode()

    send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                     "params": {"expression": expression, "returnByValue": True}}))
    while True:
        message = json.loads(receive())
        if message.get("id") == 1:
            result = message["result"]
            if "exceptionDetails" in result:
                return result["exceptionDetails"].get("text", "JS error")
            return result.get("result", {}).get("value")


def main(argv):
    what = argv[1] if len(argv) > 1 else "videos"
    expression = PRESETS.get(what, what)
    try:
        value = evaluate(expression)
    except (OSError, StopIteration) as exc:
        print(f"Cannot reach the kiosk page on port {PORT}: {exc}")
        print("Is the browser running? systemctl --user status wtp-browser")
        return 1
    if isinstance(value, str):
        try:
            print(json.dumps(json.loads(value), indent=1))
            return 0
        except ValueError:
            pass
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
