#!/usr/bin/env bash
# Get the kiosk running again, then report why git cannot update.
#
# Safe to re-run. The only things it changes are file permissions and the
# service state; it never touches the repo contents or your data.
#
#   curl -fsSL https://raw.githubusercontent.com/maartengerritse/wtp-scale/main/pi/repair.sh | bash

REPO="${WTP_REPO:-$HOME/wtp-scale}"
URL="https://github.com/maartengerritse/wtp-scale.git"

echo "=== 1. restoring execute permissions ==="
# The repo now records these as 755, but a clone made before that fix still
# has them 644, and `git reset --hard` used to strip them after every update.
chmod +x "$REPO"/pi/*.sh "$REPO"/pi/*.py "$REPO"/tools/* 2>/dev/null
echo "  kiosk.sh executable: $([ -x "$REPO/pi/kiosk.sh" ] && echo yes || echo STILL NO)"

echo
echo "=== 2. clearing the failure counter ==="
# systemd refuses to start a unit that has hit its restart limit until the
# counter is reset, so this has to happen before starting.
systemctl --user reset-failed wtp-kiosk.service wtp-browser.service 2>/dev/null
echo "  done"

echo
echo "=== 3. starting the kiosk ==="
systemctl --user start wtp-kiosk.service wtp-browser.service 2>&1
sleep 4
for unit in wtp-kiosk wtp-browser; do
  echo "  $unit: $(systemctl --user is-active $unit.service)"
done

echo
echo "=== 4. is the page being served? ==="
curl -sf -o /dev/null -w "  localhost:8080/state -> HTTP %{http_code}\n" --max-time 5 \
  http://127.0.0.1:8080/state || echo "  no answer from the reader service"

echo
echo "=== 5. why git cannot reach GitHub ==="
echo "--- the exact endpoint git uses ---"
curl -sI --max-time 20 "https://github.com/maartengerritse/wtp-scale.git/info/refs?service=git-upload-pack" \
  | head -8 | sed 's/^/  /'
echo "--- dns ---"
getent hosts github.com | sed 's/^/  /'
echo "--- git config that could rewrite or force auth ---"
git config --list --show-origin 2>/dev/null \
  | grep -iE 'credential|insteadof|extraheader|http\.|proxy' | sed 's/^/  /' \
  || echo "  (nothing relevant)"
echo "--- credential files ---"
ls -la ~/.git-credentials ~/.gitconfig 2>/dev/null | sed 's/^/  /' || echo "  (none)"

echo
echo "If step 3 shows both active, the kiosk is running again."
