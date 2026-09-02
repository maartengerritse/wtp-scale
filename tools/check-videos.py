#!/usr/bin/env python3
"""Hard gate: every kiosk video must be 8-bit H.264 with moov before mdat.

A 10-bit file (High 10 / yuv420p10le) does not decode in Chromium on any
platform, Raspberry Pi included. It shows as a black or stuck screen, and
because `canplaythrough` never fires, any overlay waiting on it never lifts.
intro.mp4 and loading.mp4 were both 10-bit before the September 2026 rebuild.
"""

import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,profile,pix_fmt,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)["streams"][0]


def atom_order(path, limit=8):
    order = []
    with open(path, "rb") as f:
        while len(order) < limit:
            head = f.read(8)
            if len(head) < 8:
                break
            size, kind = struct.unpack(">I4s", head)
            order.append(kind.decode("latin1"))
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                f.seek(size - 16, 1)
            elif size == 0:
                break
            else:
                f.seek(size - 8, 1)
    return order


def main(argv):
    # ffprobe lives on the authoring machine, not on the kiosk. Skipping is the
    # right answer on a Pi: the videos were already gated before they were
    # committed, and a missing tool is not a broken video.
    if shutil.which("ffprobe") is None:
        print("ffprobe not installed - skipping the video check.")
        print("This is expected on the Raspberry Pi; videos are checked before they are committed.")
        return 0

    directory = Path(argv[1] if len(argv) > 1 else "assets/video")
    files = sorted(directory.glob("*.mp4"))
    if not files:
        print(f"No .mp4 files in {directory}")
        return 1

    failed = False
    for path in files:
        stream = probe(path)
        profile = stream.get("profile", "?")
        pix_fmt = stream.get("pix_fmt", "?")
        problems = []

        if stream.get("codec_name") != "h264":
            problems.append(f"codec={stream.get('codec_name')}")
        if pix_fmt != "yuv420p":
            problems.append(f"pix_fmt={pix_fmt} (not 8-bit)")
        if "10" in profile:
            problems.append(f"profile={profile} (10-bit, will not decode)")

        order = atom_order(path)
        if "moov" in order and "mdat" in order and order.index("moov") > order.index("mdat"):
            problems.append("moov after mdat (slow start)")

        size_mb = path.stat().st_size / 1_000_000
        if problems:
            failed = True
            print(f"FAIL  {path.name:<24} {'; '.join(problems)}")
        else:
            dims = f"{stream.get('width')}x{stream.get('height')}"
            print(f"ok    {path.name:<24} {profile} {pix_fmt} {dims} {size_mb:.1f} MB")

    print()
    if failed:
        print("Some videos will NOT play in Chromium on the Pi.")
        return 1
    print(f"All {len(files)} videos are Pi-safe.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
