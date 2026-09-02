#!/usr/bin/env bash
# Collect everything needed to diagnose a kiosk or update problem.
#
# Run it on the Pi. Nothing here changes anything; it only reads state.
#
#   pi/debug.sh
#
# Or, when the repo itself cannot update, straight from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/maartengerritse/wtp-scale/main/pi/debug.sh | bash

REPO="${WTP_REPO:-$HOME/wtp-scale}"
OUT="$HOME/wtp-debug.txt"
URL="https://github.com/maartengerritse/wtp-scale.git"

{
echo "WTP Scale diagnostics - $(date)"
echo "host: $(hostname)   user: $(whoami)   repo: $REPO"

echo
echo "=== disk space ==="
df -h "$HOME" | tail -2
echo "inodes:"; df -i "$HOME" | tail -1

echo
echo "=== memory ==="
free -h 2>/dev/null | head -2

echo
echo "=== repo ==="
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" log --oneline -1
  echo "branch: $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>&1)"
  echo "remote: $(git -C "$REPO" remote get-url origin 2>&1)"
  echo "dirty files:"; git -C "$REPO" status --short 2>&1 | head -5
  echo "stashes:"; git -C "$REPO" stash list 2>&1 | head -5
  echo "locks:"; ls -l "$REPO"/.git/*.lock 2>/dev/null || echo "  (none)"
  echo "size: $(du -sh "$REPO" 2>/dev/null | cut -f1)  (.git: $(du -sh "$REPO/.git" 2>/dev/null | cut -f1))"
  echo "kiosk.sh executable: $([ -x "$REPO/pi/kiosk.sh" ] && echo yes || echo NO)"
else
  echo "no git repo at $REPO"
fi

echo
echo "=== network ==="
echo "git version: $(git --version)"
echo "proxy env: $(env | grep -i proxy || echo none)"
echo -n "https to github: "; curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 15 https://github.com 2>&1
echo "ls-remote from outside the repo:"
( cd "$HOME" && GIT_TERMINAL_PROMPT=0 timeout 30 git ls-remote "$URL" HEAD 2>&1 | head -3 | sed 's/^/  /' )
echo "fetch from inside the repo:"
GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$REPO" fetch origin 2>&1 | head -3 | sed 's/^/  /' || echo "  (failed)"

echo
echo "=== services ==="
for unit in wtp-kiosk wtp-browser; do
  echo "--- $unit: $(systemctl --user is-active $unit.service 2>&1) ---"
  systemctl --user --no-pager --lines=0 status $unit.service 2>&1 | head -4
done

echo
echo "=== session ==="
echo "type=${XDG_SESSION_TYPE:-unset} display=${DISPLAY:-unset} wayland=${WAYLAND_DISPLAY:-unset}"

echo
echo "=== is the page served? ==="
curl -sf -o /dev/null -w "  localhost:8080/state -> HTTP %{http_code}\n" --max-time 5 \
  http://127.0.0.1:8080/state || echo "  no answer"

echo
echo "=== recent logs, browser ==="
journalctl --user -u wtp-browser.service -n 15 --no-pager 2>&1 | tail -15
echo
echo "=== recent logs, reader ==="
journalctl --user -u wtp-kiosk.service -n 10 --no-pager 2>&1 | tail -10
} 2>&1 | tee "$OUT"

echo
echo "Saved to $OUT"
