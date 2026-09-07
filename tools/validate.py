#!/usr/bin/env python3
"""Consistency check for products.json.

Catches the failure modes that broke the previous version:
  - two products claiming the same RFID tag (Garden Trowel was unreachable
    for months because it reused Hardware Box's ID)
  - an amount left as a display string. Money is stored as a number so the
    kiosk can show it in either currency; "€0,12" would render as a literal.
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

REQUIRED = ("id", "name", "materials", "materialTotal", "distribution", "totals")
CURRENCIES = ("EUR", "USD")


def check_amounts(product, errors):
    """Every money field must be a number, not a pre-formatted string."""
    name = product.get("name", product.get("id", "<unnamed>"))

    def number(value, where):
        if isinstance(value, str):
            errors.append(f"{name}: {where} is the string {value!r}; it must be a number")
        elif value is not None and not isinstance(value, (int, float)):
            errors.append(f"{name}: {where} is not a number")

    for i, m in enumerate(product.get("materials") or []):
        number(m.get("value"), f"materials[{i}] ({m.get('label', '?')})")
    number(product.get("materialTotal"), "materialTotal")
    number((product.get("totals") or {}).get("totalCosts"), "totals.totalCosts")
    for key in ("social", "environmental", "total", "co2eq"):
        if (product.get("sustainability") or {}).get(key) is not None:
            number(product["sustainability"][key], f"sustainability.{key}")

    currency = product.get("currency")
    if currency is not None and currency not in CURRENCIES:
        errors.append(f"{name}: currency {currency!r} is not one of {CURRENCIES}")


def main():
    errors, warnings = [], []
    doc = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))
    products = doc.get("products", [])

    config = doc.get("config", {})
    if config.get("currency") not in CURRENCIES:
        print(f"ERROR  config.currency must be one of {CURRENCIES}")
        return 1
    if not isinstance(config.get("usdPerEur"), (int, float)):
        print("ERROR  config.usdPerEur must be a number")
        return 1

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
        check_amounts(p, errors)

        if not p.get("video"):
            warnings.append(f"{name}: no video yet")

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
    for orphan in sorted(on_disk - used_videos - {"intro.mp4", "intro-keyed.mp4", "loading.mp4", "loading-keyed.mp4"}):
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
    # The staged file is not loaded by the kiosk, but it must be structurally
    # sound so a product cannot be promoted broken.
    pending_path = ROOT / "products-pending.json"
    if pending_path.exists():
        pending = json.loads(pending_path.read_text(encoding="utf-8")).get("products", [])
        pending_errors = []
        for p in pending:
            for field in REQUIRED:
                if not p.get(field):
                    pending_errors.append(f"{p.get('id', '?')}: missing '{field}'")
            check_amounts(p, pending_errors)
            if p.get("id") in seen_ids:
                pending_errors.append(f"{p['id']}: id already used in products.json")
            for t in p.get("tagIds") or []:
                if str(t) in seen_tags:
                    pending_errors.append(f"{p['id']}: tag {t} already used in products.json")
        for e in pending_errors:
            print(f"ERROR  products-pending: {e}")
        errors.extend(pending_errors)
        print(f"\n{len(pending)} products staged in products-pending.json, "
              "awaiting a video and a tag")

    print(f"{len(products)} products, {sum(len(p.get('tagIds') or []) for p in products)} tags, "
          f"{len(used_videos)} videos referenced")
    if errors:
        print(f"{len(errors)} error(s) — fix before deploying.")
        return 1
    print(f"No errors. {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
