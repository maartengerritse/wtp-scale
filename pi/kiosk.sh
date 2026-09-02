#!/usr/bin/env bash
# Launch Chromium full-screen against the local kiosk service.
#
# No Selenium and no chromedriver: Chromium is started once here and is never
# driven programmatically. The page swaps its own views when a tag is read,
# so there is nothing to keep in version-step with the browser.

set -euo pipefail

PORT="${WTP_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"

export DISPLAY="${DISPLAY:-:0}"

# Pi OS Bookworm ships `chromium`; older releases ship `chromium-browser`.
if command -v chromium-browser >/dev/null 2>&1; then
  CHROME=chromium-browser
elif command -v chromium >/dev/null 2>&1; then
  CHROME=chromium
else
  echo "No Chromium found. Install it with: sudo apt install -y chromium-browser" >&2
  exit 1
fi

# Stop the screen blanking mid-conference.
if command -v xset >/dev/null 2>&1; then
  xset s off || true
  xset -dpms || true
  xset s noblank || true
fi

# Wait for the kiosk service to answer before opening the browser, otherwise
# Chromium shows its own error page and stays there.
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "${URL}state"; then break; fi
  sleep 1
done

# A crash on the previous run otherwise triggers a "restore pages?" bubble
# that sits on screen until someone dismisses it.
PROFILE="${HOME}/.config/wtp-kiosk"
mkdir -p "$PROFILE/Default"
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' \
  "$PROFILE/Default/Preferences" 2>/dev/null || true

exec "$CHROME" \
  --kiosk \
  --user-data-dir="$PROFILE" \
  --autoplay-policy=no-user-gesture-required \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=Translate,TranslateUI \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  --disable-component-update \
  "$URL"
