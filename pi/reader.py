#!/usr/bin/env python3
"""WTP Scale kiosk service.

Replaces the old Selenium setup. Two jobs in one process:

  1. Read the MFRC522 RFID reader in a background thread and remember which
     tag is currently on the scale.
  2. Serve the repo folder over HTTP on localhost, plus a /state endpoint the
     page polls to learn which tag that is.

Chromium is launched separately (see kiosk.sh) and simply opens the page. It
is never driven by this script, so there is no chromedriver to keep in step
with Chromium's version — that mismatch was a recurring source of breakage.

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

# How long a tag may go unseen before we call the scale empty. The reader
# misses reads intermittently even while a tag sits still, so a single failed
# read must not blank the screen.
TAG_GRACE_SECONDS = 0.6

# Reader poll interval. Fast enough to feel instant, slow enough to leave the
# Pi's CPU free for video decoding.
READ_INTERVAL = 0.1


class State:
    """Current tag, shared between the reader thread and the HTTP threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tag = None
        self._last_seen = 0.0

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


STATE = State()


def reader_loop(verbose=False):
    """Poll the MFRC522 forever, recording whichever tag is present."""
    try:
        import RPi.GPIO as GPIO
        from mfrc522 import SimpleMFRC522
    except ImportError as exc:
        print(f"[reader] RFID libraries unavailable ({exc}).", file=sys.stderr)
        print("[reader] Serving pages only; tags will not be detected.", file=sys.stderr)
        return

    GPIO.setwarnings(False)
    reader = SimpleMFRC522()
    print("[reader] Ready. Place a tag on the scale.")

    try:
        while True:
            try:
                tag_id, _text = reader.read_no_block()
                if tag_id:
                    if verbose:
                        print(f"[reader] tag {tag_id}")
                    STATE.saw(tag_id)
            except Exception as exc:                     # noqa: BLE001
                # A single bad read must never take the kiosk down.
                print(f"[reader] read error: {exc}", file=sys.stderr)
            time.sleep(READ_INTERVAL)
    finally:
        GPIO.cleanup()


class Handler(SimpleHTTPRequestHandler):
    """Static files from the repo root, plus /state."""

    def do_GET(self):                                    # noqa: N802
        if self.path.split("?")[0] == "/state":
            body = json.dumps({"tag": STATE.current()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # The kiosk always wants the file on disk, never a stale cached copy,
        # so an Update takes effect on the next refresh.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass                                             # quiet; systemd logs enough


def main():
    parser = argparse.ArgumentParser(description="WTP Scale kiosk service")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-reader", action="store_true",
                        help="serve pages without touching the RFID hardware")
    parser.add_argument("--verbose", action="store_true",
                        help="log every tag read")
    args = parser.parse_args()

    os.chdir(ROOT)

    if not args.no_reader:
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
