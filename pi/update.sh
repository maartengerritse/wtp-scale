#!/usr/bin/env bash
# Fetch the latest version from GitHub and restart the kiosk.
#
# Called by the Update button in the desktop app (pi/updater.py), and usable
# on its own over SSH. Written to fail clearly rather than half-apply: every
# failure below leaves the kiosk running the version it already had.
#
#   --check   report whether an update exists, change nothing
#
# Exit codes:  0 up to date or updated   1 something went wrong

set -uo pipefail

cd "$(dirname "$0")/.." || { echo "Cannot find the repo folder."; exit 1; }
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

step() { printf '\n%s\n' "$1"; }
fail() { printf '\n%s\n' "$1"; exit 1; }

# --- sanity ---------------------------------------------------------------

command -v git >/dev/null 2>&1 || fail "git is not installed."
git rev-parse --git-dir >/dev/null 2>&1 || fail \
"This folder is not a git clone, so it cannot update itself.
Re-install with:
  git clone https://github.com/maartengerritse/wtp-scale.git ~/wtp-scale"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  fail "Branch '$BRANCH' is not tracking anything on GitHub.
Fix with:  git branch --set-upstream-to=origin/main $BRANCH"
fi

# --- look for changes -----------------------------------------------------

step "Checking for updates..."
if ! git fetch --quiet origin 2>/tmp/wtp-fetch-error; then
  echo "Could not reach GitHub."
  echo
  sed 's/^/  /' /tmp/wtp-fetch-error
  fail "The kiosk is still running and unchanged. Connect to a network and try again."
fi

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "You are up to date."
  echo "  $(git log -1 --format='%h  %cd  %s' --date=format:'%d %b %Y')"
  exit 0
fi

echo "An update is available:"
echo
git --no-pager log --oneline --no-decorate "HEAD..$REMOTE" | sed 's/^/  /'

if $CHECK_ONLY; then
  echo
  echo 'Press "Update now" to install it.'
  exit 0
fi

# --- apply ----------------------------------------------------------------

# The Pi is a display device: nothing is authored on it, so local edits are
# accidents rather than work. Stash them so they are recoverable, then move
# cleanly to the remote state.
if ! git diff --quiet || ! git diff --cached --quiet; then
  step "Setting aside local changes on this Pi..."
  git stash push --include-untracked --quiet \
      -m "local changes before update $(date '+%Y-%m-%d %H:%M')" \
    && echo "  Saved. Recover them with: git stash list" \
    || fail "Could not set aside local changes; nothing has been updated."
fi

step "Downloading..."
git reset --hard "$REMOTE" --quiet || fail "Download failed; nothing has been changed."
echo "  Now at: $(git log -1 --format='%h  %s')"

step "Checking the product data..."
python3 tools/validate.py || echo "  (see the warnings above)"

step "Checking the videos..."
if python3 tools/check-videos.py >/tmp/wtp-video-check 2>&1; then
  tail -1 /tmp/wtp-video-check | sed 's/^/  /'
else
  grep -E '^(FAIL|Some)' /tmp/wtp-video-check | sed 's/^/  /'
  echo "  Those clips will not play on this Pi."
fi

step "Restarting the kiosk..."
if systemctl --user restart wtp-kiosk.service wtp-browser.service 2>/tmp/wtp-restart-error; then
  echo "  Restarted."
else
  sed 's/^/  /' /tmp/wtp-restart-error
  echo "  The files are updated. Reboot the Pi to pick them up."
fi

step "Done."
