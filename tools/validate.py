#!/usr/bin/env python3
"""Consistency check for products.json.

Catches the failure modes that broke the previous version:
  - two products claiming the same RFID tag (Garden Trowel was unreachable
    for months because it reused Hardware Box's ID)
  - a product pointing at a video file that does not exist
  - a product with no tag, which can never be shown
  - videos present on disk that nothing references

Run before every commit:  python3 tools/validate.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = ROOT / "assets" / "video"

REQUIRED = ("id", "name", "video", "materials", "materialTotal", "distribution", "totals")


def main():
    errors, warnings = [], []
    doc = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))
    products = doc.get("products", [])

    if not products:
        print("products.json contains no products")
        return 1

    seen_tags = defaultdict(list)
    seen_ids = defaultdict(list)
    used_videos = set()

    for p in products:
        name = p.get("name", p.get("id", "<unnamed>"))

        for field in REQUIRED:
            if not p.get(field):
                errors.append(f"{name}: missing required field '{field}'")

        seen_ids[p.get("id")].append(name)

        tags = p.get("tagIds") or []
        if not tags:
            warnings.append(f"{name}: no tag ID — cannot be triggered by the reader")
        for t in tags:
            seen_tags[str(t)].append(name)

        video = p.get("video")
        if video:
            used_videos.add(video)
            if not (VIDEO_DIR / video).exists():
                errors.append(f"{name}: video '{video}' not found in assets/video/")

        if p.get("_note"):
            warnings.append(f"{name}: {p['_note']}")

    for tag, owners in seen_tags.items():
        if len(owners) > 1:
            errors.append(f"tag {tag} claimed by {len(owners)} products: {', '.join(owners)}")

    for pid, owners in seen_ids.items():
        if len(owners) > 1:
            errors.append(f"duplicate product id '{pid}': {', '.join(owners)}")

    on_disk = {f.name for f in VIDEO_DIR.glob("*.mp4")}
    for orphan in sorted(on_disk - used_videos - {"intro.mp4", "loading.mp4"}):
        warnings.append(f"{orphan} is on disk but no product references it")

    shared = [v for v in used_videos if sum(1 for p in products if p.get("video") == v) > 1]
    for v in sorted(set(shared)):
        who = [p["name"] for p in products if p.get("video") == v]
        warnings.append(f"{v} is shared by: {', '.join(who)}")

    for w in warnings:
        print(f"WARN   {w}")
    for e in errors:
        print(f"ERROR  {e}")

    print()
    print(f"{len(products)} products, {sum(len(p.get('tagIds') or []) for p in products)} tags, "
          f"{len(used_videos)} videos referenced")
    if errors:
        print(f"{len(errors)} error(s) — fix before deploying.")
        return 1
    print(f"No errors. {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
