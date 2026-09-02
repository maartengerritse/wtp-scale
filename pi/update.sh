#!/usr/bin/env bash
# Pull the latest version and restart the kiosk.
# Called by the desktop Update button (updater.py) and usable on its own.

set -euo pipefail
cd "$(dirname "$0")/.."

echo "Checking for updates..."
git fetch --quiet origin

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "Already up to date ($(git log -1 --format='%h %s'))."
  exit 0
fi

echo "New version available:"
git --no-pager log --oneline HEAD.."$REMOTE" | sed 's/^/  /'

echo
echo "Downloading..."
git reset --hard "$REMOTE" --quiet     # device is read-only in practice; no local commits to keep
echo "Now at: $(git log -1 --format='%h %s')"

echo
echo "Checking data..."
python3 tools/validate.py || echo "(validation reported problems -- see above)"

echo
echo "Restarting kiosk..."
systemctl --user restart wtp-kiosk.service wtp-browser.service
echo "Done."
