#!/usr/bin/env python3
"""WTP Scale kiosk service.

Replaces the old Selenium setup. Two jobs in one process:

  1. Read the MFRC522 RFID reader in a background thread and remember which
     tag is currently on the scale.
  2. Serve the repo folder over HTTP on localhost, plus:
       GET  /state   which tag is on the scale, and whether the reader works
       POST /log     events the page reports (view changes, video restarts)

Chromium is launched separately (see kiosk.sh) and simply opens the page. It
is never driven by this script, so there is no chromedriver to keep in step
with Chromium's version -- that mismatch was a recurring source of breakage.

Everything printed here lands in the journal:
    journalctl --user -u wtp-kiosk -f

Run standalone for testing without a reader:
    python3 pi/reader.py --no-reader
"""

import argparse
import json
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products.json"

# How long a tag may go unseen before we call the scale empty. The reader
# misses reads intermittently even while a tag sits still, so a single failed
# read must not blank the screen.
TAG_GRACE_SECONDS = 0.6

# Reader poll interval. Fast enough to feel instant, slow enough to leave the
# Pi's CPU free for video decoding.
READ_INTERVAL = 0.1

# Reset-pin candidates, BOARD numbering. 22 is the mfrc522 library's default.
# With RST on the wrong pin the chip is held in reset and reads as 0x00 --
# exactly what Scale 001 showed until pin 16 turned out to be the one wired.
# WTP_RST_PIN=<n> pins it explicitly; otherwise each candidate is probed.
RST_CANDIDATES = (22, 16, 15, 18, 13, 11)
VERSION_REG = 0x37
KNOWN_VERSIONS = {0x91: "MFRC522 v1", 0x92: "MFRC522 v2",
                  0x88: "FM17522 clone", 0x12: "counterfeit MFRC522"}
REPROBE_SECONDS = 10


class State:
    """Shared between the reader thread and the HTTP threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tag = None
        self._last_seen = 0.0
        self._reader = "starting"
        self._reader_info = ""

    def saw(self, tag_id):
        with self._lock:
            self._tag = str(tag_id)
            self._last_seen = time.monotonic()

    def current(self):
        with self._lock:
            if self._tag is None:
                return None
            if time.monotonic() - self._last_seen > TAG_GRACE_SECONDS:
                self._tag = None
            return self._tag

    def set_reader(self, status, info=""):
        with self._lock:
            self._reader, self._reader_info = status, info

    def snapshot(self):
        tag = self.current()
        with self._lock:
            return {"tag": tag, "reader": self._reader, "readerInfo": self._reader_info}


STATE = State()


# ----------------------------------------------------------------- products

class TagNames:
    """tag id -> product name, reloaded whenever products.json changes."""

    def __init__(self):
        self._names = {}
        self._mtime = None
        self.refresh()

    def refresh(self):
        try:
            mtime = PRODUCTS.stat().st_mtime
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            doc = json.loads(PRODUCTS.read_text(encoding="utf-8"))
            self._names = {str(t): p.get("name", p.get("id", "?"))
                           for p in doc.get("products", []) for t in p.get("tagIds", [])}
            self._mtime = mtime
        except (OSError, ValueError) as exc:
            print(f"[reader] could not read products.json: {exc}", file=sys.stderr)

    def name(self, tag_id):
        self.refresh()
        return self._names.get(str(tag_id))


# ------------------------------------------------------------------- reader

def probe_reader(GPIO, MFRC522):
    """Return (chip, rst_pin, version) for the first reset pin the chip answers on."""
    forced = os.environ.get("WTP_RST_PIN")
    candidates = [int(forced)] if forced else list(RST_CANDIDATES)
    for pin in candidates:
        try:
            chip = MFRC522(bus=0, device=0, pin_rst=pin)
            version = chip.Read_MFRC522(VERSION_REG)
        except Exception as exc:                          # noqa: BLE001
            print(f"[reader] probe rst=BOARD{pin}: {exc}", file=sys.stderr)
            GPIO.cleanup()
            continue
        if version in KNOWN_VERSIONS:
            return chip, pin, version
        GPIO.cleanup()
    return None, None, None


def reader_loop(verbose=False):
    try:
        import RPi.GPIO as GPIO
        from mfrc522 import MFRC522, SimpleMFRC522
    except ImportError as exc:
        print(f"[reader] RFID libraries unavailable ({exc}).", file=sys.stderr)
        print("[reader] Serving pages only; tags will not be detected.", file=sys.stderr)
        STATE.set_reader("missing", "RFID libraries not installed")
        return

    GPIO.setwarnings(False)
    names = TagNames()
    simple = None
    last_probe = 0.0
    warned_missing = False
    prev_tag = None
    last_tag_time = 0.0
    read_errors = 0

    def attach():
        nonlocal simple, warned_missing
        chip, pin, version = probe_reader(GPIO, MFRC522)
        if chip is None:
            if not warned_missing:
                print("[reader] RFID reader NOT detected on any reset pin "
                      f"{RST_CANDIDATES}. Check the SPI wiring and 3.3V. "
                      f"Retrying every {REPROBE_SECONDS}s.", file=sys.stderr)
                warned_missing = True
            STATE.set_reader("missing", "no response from MFRC522")
            simple = None
            return
        # SimpleMFRC522 wraps the raw chip with the anticollision dance; give it
        # the instance that actually answered instead of its default-pin one.
        simple = SimpleMFRC522()
        simple.READER = chip
        info = f"{KNOWN_VERSIONS[version]} (0x{version:02X}) on spidev0.0, RST=BOARD{pin}"
        print(f"[reader] RFID reader OK: {info}")
        STATE.set_reader("ok", info)
        warned_missing = False

    attach()
    print("[reader] Ready. Place a tag on the scale.")

    try:
        while True:
            now = time.monotonic()
            if simple is None:
                if now - last_probe > REPROBE_SECONDS:
                    last_probe = now
                    attach()
                time.sleep(READ_INTERVAL)
                continue

            try:
                tag_id, _text = simple.read_no_block()
                read_errors = 0
            except Exception as exc:                      # noqa: BLE001
                # A single bad read must never take the kiosk down; a run of
                # them means the reader dropped off the bus, so re-probe.
                read_errors += 1
                if read_errors in (1, 20):
                    print(f"[reader] read error: {exc}", file=sys.stderr)
                if read_errors >= 20:
                    STATE.set_reader("missing", f"read errors: {exc}")
                    simple = None
                time.sleep(READ_INTERVAL)
                continue

            if tag_id:
                STATE.saw(tag_id)
                last_tag_time = now
                if str(tag_id) != prev_tag:
                    label = names.name(tag_id) or "UNKNOWN TAG (not in products.json)"
                    print(f"[reader] tag {tag_id} -> {label}")
                    prev_tag = str(tag_id)
                elif verbose:
                    print(f"[reader] tag {tag_id} still present")
            elif prev_tag and now - last_tag_time > TAG_GRACE_SECONDS:
                print(f"[reader] tag {prev_tag} removed")
                prev_tag = None

            time.sleep(READ_INTERVAL)
    finally:
        GPIO.cleanup()


# --------------------------------------------------------------------- http

class Handler(SimpleHTTPRequestHandler):
    """Static files from the repo root, plus /state and /log."""

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                    # noqa: N802
        if self.path.split("?")[0] == "/state":
            self._json(200, STATE.snapshot())
            return
        super().do_GET()

    def do_POST(self):                                   # noqa: N802
        if self.path.split("?")[0] != "/log":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "bad json"})
            return
        event = str(payload.get("event", "?"))[:40]
        data = payload.get("data", {})
        print(f"[page] {event} {json.dumps(data, ensure_ascii=False)}")
        self._json(204, {})

    def end_headers(self):
        # The kiosk always wants the file on disk, never a stale cached copy,
        # so an Update takes effect on the next refresh.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass                                             # quiet; the journal has enough


def main():
    parser = argparse.ArgumentParser(description="WTP Scale kiosk service")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-reader", action="store_true",
                        help="serve pages without touching the RFID hardware")
    parser.add_argument("--verbose", action="store_true",
                        help="log every read, not just changes")
    args = parser.parse_args()

    # Line-buffered so events show up in the journal as they happen.
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    os.chdir(ROOT)

    if args.no_reader:
        STATE.set_reader("disabled", "--no-reader")
    else:
        threading.Thread(target=reader_loop, args=(args.verbose,), daemon=True).start()

    handler = partial(Handler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"[kiosk] Serving {ROOT} on http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kiosk] Stopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
