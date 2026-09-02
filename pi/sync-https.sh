#!/usr/bin/env bash
# Update the Pi over plain HTTPS instead of git.
#
# For when `git fetch` fails but ordinary HTTPS works -- a filtering proxy, a
# captive portal, or anything else that blocks the git endpoint. GitHub serves
# a tarball of any branch over the same HTTPS that a browser uses.
#
#   curl -fsSL https://raw.githubusercontent.com/maartengerritse/wtp-scale/main/pi/sync-https.sh | bash
#
# This replaces the working files, exactly like `git reset --hard` does. Local
# edits on the Pi are overwritten; nothing is authored here, so that is the
# intent. The .git folder is left untouched, so git keeps working once the
# network does.

set -uo pipefail

REPO="${WTP_REPO:-$HOME/wtp-scale}"
BRANCH="${1:-main}"
TARBALL="https://codeload.github.com/maartengerritse/wtp-scale/tar.gz/refs/heads/${BRANCH}"

[ -d "$REPO" ] || { echo "No repo at $REPO"; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${BRANCH} over HTTPS..."
if ! curl -fsSL --max-time 600 "$TARBALL" -o "$TMP/repo.tar.gz"; then
  echo "Download failed. HTTPS to codeload.github.com is not working either."
  exit 1
fi

echo "  $(du -h "$TMP/repo.tar.gz" | cut -f1) downloaded"

echo "Unpacking..."
tar -xzf "$TMP/repo.tar.gz" -C "$TMP" || { echo "Could not unpack."; exit 1; }
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'wtp-scale-*' | head -1)"
[ -d "$SRC" ] || { echo "Unexpected archive layout."; exit 1; }

echo "Applying to $REPO (leaving .git alone)..."
# --delete would remove .git, so copy over the top instead and accept that a
# file deleted upstream lingers until git works again.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude='.git' "$SRC"/ "$REPO"/ || { echo "Copy failed."; exit 1; }
else
  cp -a "$SRC"/. "$REPO"/ || { echo "Copy failed."; exit 1; }
fi

chmod +x "$REPO"/pi/*.sh "$REPO"/pi/*.py "$REPO"/tools/* 2>/dev/null

echo "Checking the product data..."
python3 "$REPO/tools/validate.py" 2>&1 | tail -3

echo "Restarting the kiosk..."
systemctl --user reset-failed wtp-kiosk.service wtp-browser.service 2>/dev/null
if systemctl --user restart wtp-kiosk.service wtp-browser.service 2>/dev/null; then
  sleep 4
  for unit in wtp-kiosk wtp-browser; do
    echo "  $unit: $(systemctl --user is-active $unit.service)"
  done
else
  echo "  Could not restart; reboot to pick up the changes."
fi

echo
echo "Done. Files now match branch '${BRANCH}' on GitHub."
echo "Note: git history is unchanged, so update.sh will still report an update"
echo "available until the git endpoint works again."
