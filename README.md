# WTP Scale — "What's the price?" kiosk

A Raspberry Pi hidden inside a scale. A welcome screen invites visitors to place
a product on it; an RFID tag in the product is read, a "calculating" screen runs,
and the product's cost breakdown appears.

Everything runs **fully offline**. There is no CDN, no font service, no external
image host — the rig has to work on a conference floor with no usable network.

---

## Adding a product

Three steps, no HTML.

1. Put the video in `assets/video/` (see [Videos](#videos) for the format).
2. Add an entry to `products.json`.
3. Run `python3 tools/validate.py`, commit, then press **Update** on each Pi.

A minimal entry:

```json
{
  "id": "garden-rake",
  "tagIds": ["584608700713"],
  "name": "Garden Rake",
  "subtitle": "Steel & wood, 1 piece",
  "video": "product-10.mp4",
  "currency": "EUR",
  "materials": [{ "label": "Steel head", "value": 0.42 }],
  "materialTotal": 0.42,
  "distribution": [
    { "label": "Direct Materials", "value": "48.0%", "bold": true },
    { "label": "Direct Labour (China)", "value": "2.1%" },
    { "label": "Manufacturing Overhead", "value": "9.4%" },
    { "label": "Cost of Sales", "value": "59.5%", "bold": true },
    { "label": "GSA & Other Expenses", "value": "33.0%" },
    { "label": "Profit before Taxes", "value": "7.5%" }
  ],
  "totals": { "exWorks": "100%", "totalCosts": 0.88 }
}
```

Optional blocks — **leave them out and they simply do not appear on screen**:

```json
"specs": {
  "dimensions": "45×8×3CM", "weight": "0.65KG",
  "ean": "4012345678901", "naics": "332216",
  "origin": { "country": "Germany", "code": "de" }
},
"sustainability": {
  "social": 0.18, "environmental": 0.92,
  "total": 1.10, "co2eq": 0.88
}
```

### Money and currency

**Amounts are numbers, not strings** — `0.42`, never `"€0,42"`. The kiosk can
display either currency, so it needs to convert, and it formats the result
itself: comma decimal separator, the source's own precision, and the right
symbol. Percentages stay strings because they do not convert.

`"currency"` on a product says which currency Buynamics exported it in — the
figures are never rewritten, only converted for display. Products without it
inherit `config.currency`. Today the four exported in USD are Nitrile Gloves,
AA Battery, Screwdriver and Abrasive Sponges.

`config.usdPerEur` is the rate, in one place. The Pi is offline and cannot
look one up, so **converted figures are approximate and the screen does not
say so** — worth remembering before showing a customer a converted price.

### Adding a product that has no video or tag yet

Cost data usually arrives before the video and the RFID tag. Put the entry in
`products-pending.json`, which the kiosk does not load, and move it across
when both exist:

```bash
python3 tools/promote-pending.py            # what is waiting
python3 tools/promote-pending.py aa-battery # asks for the video and tag
```

### Timing

`config` at the top of `products.json`:

| Key | Meaning |
|---|---|
| `loadingSeconds` | How long the "calculating" checklist runs before the product appears |
| `returnDelaySeconds` | How long after the product is lifted before the welcome screen returns |
| `wrapBeforeEndSeconds` | Restart the welcome clip this far before its end. The Pi cannot decode its last ~3 s, so 3.5 skips frames nobody would see and avoids a visible freeze. Other clips loop normally |

`origin.code` picks the flag from `assets/img/flags/`. Only `cn`, `de` and `gb`
exist so far; add a new SVG there for other countries.

### Tag IDs

Read the tag with any NFC app on your phone and paste the decimal ID into
`tagIds`. A product can have several tags; two products can never share one —
`validate.py` refuses that, which is the bug that kept Garden Trowel off the
screen for months.

---

## Videos

Chromium on the Pi **cannot decode 10-bit H.264**. A 10-bit file shows as a black
or frozen screen. The old `intro.mp4` and `loading.mp4` were both 10-bit — that
is the video problem that used to be so hard to pin down.

Convert anything new before committing it:

```bash
tools/encode-videos.sh incoming/ assets/video/
```

Then confirm:

```bash
python3 tools/check-videos.py
```

It must print **"All videos are Pi-safe."** The target is H.264 High profile,
8-bit `yuv420p`, level 4.0, 1920×1080, `+faststart`.

---

## Installing on a Raspberry Pi

```bash
git clone https://github.com/maartengerritse/wtp-scale.git ~/wtp-scale
~/wtp-scale/pi/install.sh
```

That installs the packages, enables SPI for the reader, registers two services
so the kiosk starts on boot and restarts if it crashes, and puts a **WTP Scale**
icon on the desktop.

### The desktop app

Double-click **WTP Scale** on the Pi desktop:

| Button | Does |
|---|---|
| Check for updates | Asks GitHub whether a newer version exists |
| Update now | Downloads it, validates the data, restarts the kiosk |
| Start kiosk | Brings the kiosk up |
| Stop kiosk | Drops back to the desktop, to work on the Pi |
| Restart kiosk | Restarts without downloading |
| Show status | Whether the reader is running, and the data check |
| Log | Live feed of tag reads (`tag read -> product -> id`, or `tag not recognised -> ignored`), screen changes and reader health |
| Currency | Switches the product pages between EUR and USD. Applies within a second; no restart needed |

A line under the title shows whether the kiosk is currently running.

The currency choice is stored in `.wtp-settings.json`, which is deliberately
untracked: it belongs to that Pi and survives every update. The two scales can
therefore be set differently.

Updates need the Pi online — do it at the hotel or office, not on the stand.

### Wiring

The MFRC522 reader connects over SPI:

| Reader | Pi (BOARD) |
|---|---|
| SDA | 24 |
| SCK | 23 |
| MOSI | 19 |
| MISO | 21 |
| GND | 6 |
| RST | 22 (auto-detected, see below) |
| 3.3V | 1 |

With RST on the wrong pin the chip is held in reset and reads as dead, so the
service probes pins 22, 16, 15, 18, 13 and 11 at startup and logs which one
answered (`journalctl --user -u wtp-kiosk`). Set `WTP_RST_PIN` to force one.
While the reader is not answering, the welcome screen shows a small
"RFID reader not detected" note in the corner.

---

## How it works

```
pi/reader.py     reads the RFID reader, serves the folder on localhost:8080
                 and exposes /state with the tag currently on the scale
pi/kiosk.sh      opens Chromium in kiosk mode at that address
assets/js/       polls /state and swaps between welcome / loading / product
```

The page **loads once and never navigates**. Scanning a tag swaps a CSS class,
so there is no reload and no black flash between screens.

There is no Selenium and no chromedriver. The previous version drove Chromium
through Selenium, which meant a Chromium update could break the kiosk until a
matching chromedriver was installed.

### Local development

No Pi and no reader needed:

```bash
python3 pi/reader.py --no-reader
```

Then open <http://localhost:8080/?dev> and press **1**–**9**/**0** to simulate
placing a product on the scale, **Escape** to lift it.

---

## Tools

| Command | Purpose |
|---|---|
| `python3 tools/validate.py` | Duplicate tags, missing videos, untagged products |
| `python3 tools/check-videos.py` | Every video is Pi-decodable |
| `tools/encode-videos.sh` | Convert new footage to the Pi-safe format |
| `tools/key-video.sh` | Replace a clip's blue studio background with the brand orange |
| `tools/add-product.py` | Add a product by answering questions |
| `tools/promote-pending.py` | Move a staged product into products.json once it has a video and a tag |
| `pi/inspect.py` | Ask the live kiosk page about its videos and current view |
| `pi/debug.sh` | Collect everything needed to diagnose a problem on the Pi |

Tag reads and screen changes are logged together: `journalctl --user -u wtp-kiosk -f`

---

## Layout

```
products.json     all product data — the only file you normally edit
index.html        the single page
assets/           css, js, fonts, img, video
pi/               reader service, kiosk launcher, services, updater app
tools/            validation and video tooling
```

`DATA-ISSUES.md` lists cost figures that do not reconcile and still need a
decision.
