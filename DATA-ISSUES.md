# Open data questions

Figures that do not reconcile, found while consolidating the old hand-edited
pages into `products.json`. **Nothing here has been changed** — the numbers on
screen are exactly the numbers that were on the old pages. These need a
decision from someone who knows the source data.

`tools/validate.py` prints a reminder for each of these until they are resolved.

---

## 1. Shower Gel — Direct Materials percentage

Shown: **53.8%**

- The three components should sum to Cost of Sales: `53.8 + 0.8 + 5.3 = 59.9%`,
  but Cost of Sales is given as **49.3%**.
- Working the other way: Total Costs €0,938 × 53.8% = €0,505, but Total Material
  Costs is given as **€0,405**.
- Both discrepancies disappear if Direct Materials is **43.2%**:
  `43.2 + 0.8 + 5.3 = 49.3%` ✓ and `€0,938 × 43.2% = €0,405` ✓

**Likely a typo for 43.2%**, but not changed without confirmation.

## 2. Binder — Total Costs

Shown: **€0,0336**

- Total Material Costs is €0,242 at 72,2% of the total, which implies a total of
  about **€0,335**.
- €0,0336 is an order of magnitude smaller than its own material costs, which
  cannot be right.

**Likely a misplaced decimal for €0,336.**

Separately, the Binder percentages do not close either: `72,2 + 1.8 + 7.1 = 81.1%`
against a stated Cost of Sales of **80.1%**, and `80.1 + 16.7 + 1.1 = 97.9%`
rather than 100%. Which of those three figures is wrong cannot be determined
from the page alone.

Note also that this product writes `72,2%` with a comma where every other
percentage on every other product uses a full stop.

## 3. Garden Saw — Total Material Costs

Shown: **€0,925** (from the v0 export; this product never had an offline page)

- Total Costs €1,374 × Direct Materials 34.2% = **€0,470**, which is exactly the
  first material line (Kraft Cardboard) rather than the sum of all four.
- The percentages themselves are internally consistent:
  `34.2 + 2.3 + 12.6 = 49.1%` ✓ and `49.1 + 43.0 + 7.9 = 100%` ✓

So either the material lines or the 34.2% is wrong. Hardware Box and Garden
Trowel, from the same export, both reconcile perfectly, which suggests the
error is specific to this product.

---

## Products that check out

Photo Frame, Storage Box, Abrasive Sponges, Swivel Castor, Hardware Box,
Garden Trowel and Smartphone all reconcile on every test:
components sum to Cost of Sales, the three top-level shares sum to 100%, and
Total Costs × Direct Materials % matches Total Material Costs.

---

## Still missing

| Product | Needs |
|---|---|
| Garden Trowel | RFID tag ID — the old script gave it Hardware Box's ID, so it has never once displayed |
| Smartphone | RFID tag ID, and its own video (currently reuses the Abrasive Sponges clip) |
| Photo Frame, Swivel Castor, Shower Gel, Binder, Smartphone | dimensions, EAN, NAICS, country of origin, and the four sustainability figures |

Fields left blank simply do not render, so these products display correctly
today — just with fewer sections than the five complete ones.
