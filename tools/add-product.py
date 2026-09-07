#!/usr/bin/env python3
"""Add a product to products.json by answering questions.

    python3 tools/add-product.py

Nothing is written until the end, and it shows you the entry first. Optional
sections can be skipped with Enter -- a field left blank simply does not
render on the kiosk, so a half-known product still displays correctly.

To edit an existing product, open products.json directly; this only adds.
"""

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = ROOT / "products.json"
VIDEO_DIR = ROOT / "assets" / "video"
FLAG_DIR = ROOT / "assets" / "img" / "flags"


def ask(prompt, default="", required=False):
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip() or default
        if value or not required:
            return value
        print("  Required.")


def pct(value):
    """Accept 48, 48.0 or 48% and always store 48%.

    The kiosk renders these strings verbatim, so a missing sign would show a
    bare number next to correctly signed ones.
    """
    value = value.strip()
    if not value:
        return ""
    return value if value.endswith("%") else value + "%"


def ask_pairs(what, example):
    """Collect label/value rows until a blank line."""
    print(f"\n{what}  (blank line when done)")
    print(f"  e.g. {example}")
    rows = []
    while True:
        label = input("  label: ").strip()
        if not label:
            return rows
        value = input("  value: ").strip()
        if not value:
            print("  Needs a value; skipping that row.")
            continue
        rows.append({"label": label, "value": value})


def main():
    doc = json.loads(PRODUCTS.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    existing_ids = {p["id"] for p in doc["products"]}
    existing_tags = {t for p in doc["products"] for t in p.get("tagIds", [])}

    print("Add a product\n" + "=" * 13)

    # --- identity ---------------------------------------------------------
    name = ask("Product name (e.g. Garden Rake)", required=True)
    default_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    while True:
        pid = ask("Short id", default_id, required=True)
        if pid not in existing_ids:
            break
        print(f"  '{pid}' is already used.")

    subtitle = ask("Subtitle (e.g. Steel & wood, 1 piece)")

    # --- tags -------------------------------------------------------------
    print("\nRFID tag IDs, decimal, from your phone's NFC app. Blank line when done.")
    tag_ids = []
    while True:
        tag = input("  tag id: ").strip()
        if not tag:
            break
        if not tag.isdigit():
            print("  Should be digits only.")
            continue
        if tag in existing_tags:
            owner = next(p["name"] for p in doc["products"] if tag in p.get("tagIds", []))
            print(f"  Already used by {owner}. Two products cannot share a tag.")
            continue
        tag_ids.append(tag)
        existing_tags.add(tag)
    if not tag_ids:
        print("  No tag: the product will be in the file but the reader cannot trigger it.")

    # --- video ------------------------------------------------------------
    available = sorted(f.name for f in VIDEO_DIR.glob("*.mp4"))
    print(f"\nVideos in assets/video/: {', '.join(available)}")
    while True:
        video = ask("Video filename", required=True)
        if (VIDEO_DIR / video).exists():
            break
        print(f"  {video} is not in assets/video/. Put it there first "
              f"(run tools/encode-videos.sh on it), or type an existing name.")

    # --- cost data --------------------------------------------------------
    materials = ask_pairs("Direct material costs", "Kraft Cardboard (CHN)  /  €0,470")
    material_total = ask("Total material costs (e.g. €0,925)")

    print("\nCost distribution percentages. The % sign is added for you.")
    dm = pct(ask("  Direct Materials %"))
    dl_label = ask("  Direct labour label", "Direct Labour (China)")
    dl = pct(ask("  Direct labour %"))
    oh = pct(ask("  Manufacturing Overhead %"))
    cos = pct(ask("  Cost of Sales %"))
    gsa = pct(ask("  GSA & Other Expenses %"))
    pbt = pct(ask("  Profit before Taxes %"))

    distribution = []
    for label, value, bold in (
        ("Direct Materials", dm, True), (dl_label, dl, False),
        ("Manufacturing Overhead", oh, False), ("Cost of Sales", cos, True),
        ("GSA & Other Expenses", gsa, False), ("Profit before Taxes", pbt, False),
    ):
        if value:
            row = {"label": label, "value": value}
            if bold:
                row["bold"] = True
            distribution.append(row)

    total_costs = ask("\nTotal Costs (e.g. €1,374)")

    # --- optional ---------------------------------------------------------
    print("\nOptional details -- press Enter to skip any of them.")
    specs = OrderedDict()
    for key, prompt in (("dimensions", "Dimensions (e.g. 45×8×3CM)"),
                        ("weight", "Weight (e.g. 0.65KG)"),
                        ("ean", "EAN code"), ("naics", "NAICS code")):
        specs[key] = ask(f"  {prompt}")

    country = ask("  Country of origin (e.g. Germany)")
    if country:
        flags = sorted(f.stem for f in FLAG_DIR.glob("*.svg"))
        code = ask(f"  Flag code, one of {', '.join(flags)}")
        if code and not (FLAG_DIR / f"{code}.svg").exists():
            print(f"  No flag {code}.svg yet -- add one to assets/img/flags/ "
                  f"or the flag will not show.")
        specs["origin"] = {"country": country, "code": code}

    sustainability = OrderedDict()
    for key, prompt in (("social", "Social (e.g. €0,18)"),
                        ("environmental", "Environmental"),
                        ("total", "Total"), ("co2eq", "CO₂-eq")):
        sustainability[key] = ask(f"  {prompt}")

    # --- assemble ---------------------------------------------------------
    entry = OrderedDict()
    entry["id"] = pid
    entry["tagIds"] = tag_ids
    entry["name"] = name
    if subtitle:
        entry["subtitle"] = subtitle
    entry["video"] = video
    if any(v for k, v in specs.items() if k != "origin") or "origin" in specs:
        entry["specs"] = specs
    entry["materials"] = materials
    if material_total:
        entry["materialTotal"] = material_total
    entry["distribution"] = distribution
    entry["totals"] = {"exWorks": "100%", "totalCosts": total_costs}
    if any(sustainability.values()):
        entry["sustainability"] = sustainability

    print("\n" + "-" * 60)
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    print("-" * 60)

    if ask("\nAdd this to products.json? (y/n)", "y").lower() not in ("y", "yes"):
        print("Nothing written.")
        return 1

    doc["products"].append(entry)
    PRODUCTS.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nAdded {name} to products.json.")
    print("Now run:  python3 tools/validate.py")
    print("Then commit and press Update on each Pi.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing written.")
        sys.exit(1)
