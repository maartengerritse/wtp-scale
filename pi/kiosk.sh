#!/usr/bin/env bash
# Launch Chromium full-screen against the local kiosk service.
#
# No Selenium and no chromedriver: Chromium is started once here and is never
# driven programmatically. The page swaps its own views when a tag is read,
# so there is nothing to keep in version-step with the browser.

set -euo pipefail

PORT="${WTP_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/"

# Work out how to talk to the screen.
#
# Pi OS Bookworm runs Wayland (Wayfire), but Chromium's native Wayland backend
# does not accept the compositor's fullscreen size here: --kiosk and
# --start-fullscreen both apply, and the window still comes up about 500x40 in
# the corner. Verified on Scale 001 by screenshotting a live instance both
# ways. Under XWayland the same flags give a correct 1920x1080 kiosk, so X11
# is the default even on a Wayland desktop.
#
# Set WTP_USE_WAYLAND=1 to force the native Wayland backend instead.
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XDG_RUNTIME_DIR="$RUNTIME_DIR"

# At boot this service starts with the user session, typically before Wayfire
# has brought up XWayland. Wait for a display socket rather than fail and
# burn through the restart limit while the desktop is still loading.
for _ in $(seq 1 90); do
  ls /tmp/.X11-unix/X* "$RUNTIME_DIR"/wayland-* >/dev/null 2>&1 && break
  sleep 1
done

if [ "${WTP_USE_WAYLAND:-0}" = "1" ] && [ -n "${WAYLAND_DISPLAY:-}" ]; then
  SESSION=wayland
  OZONE=(--ozone-platform=wayland)
else
  SESSION=x11
  # Pi OS's chromium-browser wrapper adds --ozone-platform=wayland by itself
  # when the session looks like Wayland, so simply unsetting WAYLAND_DISPLAY
  # left it trying Wayland with no socket ("Failed to connect to Wayland
  # display"). Our flags are appended after the wrapper's, and Chromium takes
  # the last value for a switch, so name x11 explicitly to win.
  OZONE=(--ozone-platform=x11)
  unset WAYLAND_DISPLAY
  export XDG_SESSION_TYPE=x11
  # XWayland is normally :0 under Wayfire; fall back to whatever socket exists.
  if [ -z "${DISPLAY:-}" ]; then
    for sock in /tmp/.X11-unix/X*; do
      case "$sock" in *'*') break;; esac
      export DISPLAY=":${sock##*/X}"
      break
    done
    export DISPLAY="${DISPLAY:-:0}"
  fi
  # Under a real X11 session the cookie is needed; harmless under XWayland.
  if [ -z "${XAUTHORITY:-}" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
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

# Start from a clean profile every time.
#
# Chromium saves its window geometry and restores it on the next launch, which
# happens AFTER --start-fullscreen is applied. A profile written while the
# window was wrong therefore shrinks every subsequent launch back to the wrong
# size: the window opens full screen for a moment and then collapses. The
# kiosk keeps no state worth preserving -- no logins, no history, and the page
# is served from localhost -- so discarding the profile makes each start
# deterministic and also clears any "restore pages?" bubble from a crash.
PROFILE="${HOME}/.config/wtp-kiosk"
rm -rf "$PROFILE"
mkdir -p "$PROFILE"

# --kiosk hides the browser chrome but does not size the window: Chromium's
# Wayland backend leaves that entirely to the compositor and ignores
# --window-size. Under Wayfire that produced a 450x120 window in the corner.
# --start-fullscreen is what actually claims the display.
#
# The DevTools port is bound to 127.0.0.1 only; pi/inspect.py uses it to ask
# the live page about its video state, which is how the loop stall was found.
echo "kiosk: launching $CHROME at $URL"
exec "$CHROME" \
  ${OZONE[@]+"${OZONE[@]}"} \
  --kiosk \
  --start-fullscreen \
  --remote-debugging-port=9222 \
  --no-first-run \
  --no-default-browser-check \
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
