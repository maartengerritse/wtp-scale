#!/usr/bin/env python3
"""Move a staged product into the live products.json.

Products arrive from Buynamics with complete cost data but no video and no RFID
tag, so they wait in products-pending.json where the kiosk does not load them.
This moves one across once both exist.

    python3 tools/promote-pending.py              # list what is waiting
    python3 tools/promote-pending.py aa-battery   # promote one

It refuses a video that is not in assets/video/ and a tag another product
already claims -- the two mistakes that would otherwise reach a Pi.
"""

import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products.json"
PENDING = ROOT / "products-pending.json"
VIDEO_DIR = ROOT / "assets" / "video"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def save(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def main(argv):
    if not PENDING.exists():
        print("Nothing staged: products-pending.json does not exist.")
        return 1

    pending = load(PENDING)
    waiting = pending.get("products", [])

    if len(argv) < 2:
        print("Waiting for a video and a tag:\n")
        for p in waiting:
            origin = (p.get("specs") or {}).get("origin") or {}
            print(f"  {p['id']:<18} {p['name']:<18} {p.get('currency', 'EUR')}  "
                  f"{origin.get('country', '')}")
        print("\nPromote one with:  python3 tools/promote-pending.py <id>")
        return 0

    pid = argv[1]
    entry = next((p for p in waiting if p["id"] == pid), None)
    if entry is None:
        print(f"No staged product with id '{pid}'. Run without arguments to list them.")
        return 1

    live = load(PRODUCTS)
    used_ids = {p["id"] for p in live["products"]}
    used_tags = {str(t): p["name"] for p in live["products"] for t in p.get("tagIds") or []}

    if pid in used_ids:
        print(f"'{pid}' is already in products.json.")
        return 1

    print(f"\nPromoting {entry['name']}\n")

    # --- video ------------------------------------------------------------
    available = sorted(f.name for f in VIDEO_DIR.glob("*.mp4"))
    print("Videos in assets/video/:")
    print("  " + ", ".join(available) + "\n")
    while True:
        video = ask("Video filename")
        if not video:
            print("  A video is required. Add it to assets/video/ first "
                  "(tools/encode-videos.sh), then run this again.")
            return 1
        if (VIDEO_DIR / video).exists():
            break
        print(f"  {video} is not in assets/video/.")

    # --- tags -------------------------------------------------------------
    print("\nRFID tag IDs, decimal. Blank line when done.")
    tags = []
    while True:
        tag = input("  tag id: ").strip()
        if not tag:
            break
        if not tag.isdigit():
            print("  Digits only.")
            continue
        if tag in used_tags:
            print(f"  Already used by {used_tags[tag]}. Two products cannot share a tag.")
            continue
        tags.append(tag)
        used_tags[tag] = entry["name"]
    if not tags:
        print("\n  No tag given: the product would be on the kiosk but unreachable "
              "by the reader.")
        if ask("  Promote anyway? (y/n)", "n").lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 1

    entry["video"] = video
    entry["tagIds"] = tags

    live["products"].append(entry)
    pending["products"] = [p for p in waiting if p["id"] != pid]

    save(PRODUCTS, live)
    save(PENDING, pending)

    print(f"\n{entry['name']} moved into products.json.")
    print(f"{len(pending['products'])} still staged.")
    print("\nNow run:  python3 tools/validate.py")
    print("Then commit and press Update on each Pi.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing changed.")
        sys.exit(1)
