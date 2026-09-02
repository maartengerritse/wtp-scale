#!/usr/bin/env bash
# Launch Chromium full-screen against the local kiosk service.
#
# No Selenium and no chromedriver: Chromium is started once here and is never
# driven programmatically. The page swaps its own views when a tag is read,
# so there is nothing to keep in version-step with the browser.

set -euo pipefail

PORT="${WTP_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"

# Work out how to talk to the screen. A systemd user service does not inherit
# the desktop session's environment, so this has to be discovered rather than
# assumed: Pi OS Bookworm runs Wayland by default, older releases run X11, and
# under X11 a missing XAUTHORITY makes Chromium fail with nothing on screen.
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XDG_RUNTIME_DIR="$RUNTIME_DIR"

if [ -z "${WAYLAND_DISPLAY:-}" ]; then
  for sock in "$RUNTIME_DIR"/wayland-*; do
    case "$sock" in *'*') break;; esac          # no match, glob left literal
    [ -S "$sock" ] && export WAYLAND_DISPLAY="$(basename "$sock")" && break
  done
fi

if [ -n "${WAYLAND_DISPLAY:-}" ]; then
  SESSION=wayland
  OZONE=(--ozone-platform=wayland)
else
  SESSION=x11
  OZONE=()
  export DISPLAY="${DISPLAY:-:0}"
  # Under X11 the service needs the cookie to open the display at all.
  if [ -z "${XAUTHORITY:-}" ]; then
    for xauth in "$HOME/.Xauthority" "$RUNTIME_DIR/gdm/Xauthority"; do
      [ -f "$xauth" ] && export XAUTHORITY="$xauth" && break
    done
  fi
fi

echo "kiosk: session=$SESSION display=${WAYLAND_DISPLAY:-${DISPLAY:-none}} xauth=${XAUTHORITY:-none}"

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
ready=false
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "${URL}state"; then ready=true; break; fi
  sleep 1
done
if ! $ready; then
  echo "kiosk: the reader service never answered on ${URL} -- not launching the browser." >&2
  echo "kiosk: check with: journalctl --user -u wtp-kiosk -n 30" >&2
  exit 1
fi

# Chromium otherwise asks the system keyring to hold its secrets, and on a
# fresh Pi that pops a "Choose password for keyring" dialog on top of the
# kiosk. --password-store=basic keeps it out of the keyring entirely; the
# kiosk signs into nothing, so there are no secrets worth protecting.

# A crash on the previous run otherwise triggers a "restore pages?" bubble
# that sits on screen until someone dismisses it.
PROFILE="${HOME}/.config/wtp-kiosk"
mkdir -p "$PROFILE/Default"
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/' \
  "$PROFILE/Default/Preferences" 2>/dev/null || true

echo "kiosk: launching $CHROME at $URL"
exec "$CHROME" \
  ${OZONE[@]+"${OZONE[@]}"} \
  --kiosk \
  --user-data-dir="$PROFILE" \
  --autoplay-policy=no-user-gesture-required \
  --password-store=basic \
  --use-mock-keychain \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=Translate,TranslateUI \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  --disable-component-update \
  "$URL"
