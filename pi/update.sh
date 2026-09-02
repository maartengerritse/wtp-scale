#!/usr/bin/env bash
# Fetch the latest version from GitHub and restart the kiosk.
#
# Called by the Update button in the desktop app (pi/updater.py), and usable
# on its own over SSH. Written to fail clearly rather than half-apply: every
# failure below leaves the kiosk running the version it already had.
#
#   --check   report whether an update exists, change nothing
#
# Two routes to GitHub. Normally git. But some networks serve ordinary HTTPS
# while refusing git's endpoint -- which stranded Scale 001 with no way to
# update at all -- so this falls back to GitHub's REST API and tarball, over
# the same HTTPS a browser uses.
#
# Exit codes:  0 up to date or updated   1 something went wrong

set -uo pipefail

# This script updates the folder it lives in, which means `git reset --hard`
# rewrites this very file while bash is still reading it. Bash reads scripts
# lazily by byte offset, so a changed file mid-run makes it resume at the
# wrong place. Run from a throwaway copy so the update cannot pull the file
# out from under the running shell.
if [ "${WTP_REEXEC:-}" != "1" ]; then
  WTP_REPO="$(cd "$(dirname "$0")/.." && pwd)" || { echo "Cannot find the repo folder."; exit 1; }
  COPY="$(mktemp "${TMPDIR:-/tmp}/wtp-update.XXXXXX")" || exit 1
  cp "$0" "$COPY" || exit 1
  WTP_REEXEC=1 WTP_REPO="$WTP_REPO" bash "$COPY" "$@"
  code=$?
  rm -f "$COPY"
  exit $code
fi

cd "${WTP_REPO:?}" || { echo "Cannot find the repo folder."; exit 1; }

OWNER_REPO="maartengerritse/wtp-scale"
VERSION_FILE=".wtp-version"          # records the sha applied over HTTPS
CHECK_ONLY=false
[ "${1:-}" = "--check" ] && CHECK_ONLY=true

step() { printf '\n%s\n' "$1"; }
fail() { printf '\n%s\n' "$1"; exit 1; }

# --------------------------------------------------------------- shared tail

post_update() {
  step "Checking the product data..."
  python3 tools/validate.py || echo "  (see the warnings above)"

  step "Checking the videos..."
  if python3 tools/check-videos.py >/tmp/wtp-video-check 2>&1; then
    grep -v '^ok ' /tmp/wtp-video-check | grep -v '^$' | sed 's/^/  /'
  else
    grep -E '^(FAIL|Some)' /tmp/wtp-video-check | sed 's/^/  /'
    echo "  Those clips will not play on this Pi."
  fi

  step "Restarting the kiosk..."
  systemctl --user reset-failed wtp-kiosk.service wtp-browser.service 2>/dev/null
  if systemctl --user restart wtp-kiosk.service wtp-browser.service 2>/tmp/wtp-restart-error; then
    echo "  Restarted."
  else
    sed 's/^/  /' /tmp/wtp-restart-error
    echo "  The files are updated. Reboot the Pi to pick them up."
  fi

  step "Done."
}

# ---------------------------------------------------------------- https path

https_remote_sha() {
  local sha
  # The REST API is the clean answer, but it is rate limited to 60 requests an
  # hour per address and may be blocked where the git endpoint is. The commit
  # atom feed lives on plain github.com and has neither limitation, so try both.
  sha="$(curl -fsSL --max-time 30 \
    -H "Accept: application/vnd.github.sha" \
    "https://api.github.com/repos/${OWNER_REPO}/commits/${1}" 2>/dev/null)"
  case "$sha" in
    [0-9a-f][0-9a-f]*) printf '%s' "$sha"; return 0 ;;
  esac

  sha="$(curl -fsSL --max-time 30 \
    "https://github.com/${OWNER_REPO}/commits/${1}.atom" 2>/dev/null \
    | grep -o 'Grit::Commit/[0-9a-f]\{40\}' | head -1 | cut -d/ -f2)"
  case "$sha" in
    [0-9a-f][0-9a-f]*) printf '%s' "$sha"; return 0 ;;
  esac
  return 1
}

https_local_sha() {
  # After an HTTPS sync the git history is untouched, so HEAD is stale; the
  # marker file is the honest answer to "what is actually on disk".
  if [ -s "$VERSION_FILE" ]; then cat "$VERSION_FILE"; else git rev-parse HEAD 2>/dev/null; fi
}

https_apply() {
  local sha="$1" tmp src
  tmp="$(mktemp -d)" || return 1

  echo "  downloading..."
  if ! curl -fsSL --max-time 600 \
      "https://codeload.github.com/${OWNER_REPO}/tar.gz/${sha}" -o "$tmp/repo.tar.gz"; then
    rm -rf "$tmp"; return 1
  fi
  tar -xzf "$tmp/repo.tar.gz" -C "$tmp" || { rm -rf "$tmp"; return 1; }
  src="$(find "$tmp" -maxdepth 1 -type d -name 'wtp-scale-*' | head -1)"
  [ -d "$src" ] || { rm -rf "$tmp"; return 1; }

  echo "  applying..."
  # .git is excluded: leaving history intact means git resumes normally once
  # the network allows it.
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude='.git' "$src"/ ./ || { rm -rf "$tmp"; return 1; }
  else
    cp -a "$src"/. ./ || { rm -rf "$tmp"; return 1; }
  fi
  chmod +x pi/*.sh pi/*.py tools/* 2>/dev/null
  echo "$sha" > "$VERSION_FILE"
  rm -rf "$tmp"
}

run_https_update() {
  local remote local_sha
  remote="$(https_remote_sha "$BRANCH")"
  [ -n "$remote" ] || fail "Could not reach GitHub over git or HTTPS. The kiosk is unchanged."
  local_sha="$(https_local_sha)"

  if [ "$local_sha" = "$remote" ]; then
    echo "You are up to date. (checked over HTTPS)"
    echo "  ${remote:0:7}"
    exit 0
  fi

  echo "An update is available: ${remote:0:7}"
  if $CHECK_ONLY; then
    echo
    echo 'Press "Update now" to install it.'
    exit 0
  fi

  step "Downloading over HTTPS..."
  https_apply "$remote" || fail "Update failed. The kiosk is unchanged."
  echo "  Now at: ${remote:0:7}"
  post_update
  exit 0
}

# ------------------------------------------------------------------- sanity

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

# ------------------------------------------------------------ look for changes

step "Checking for updates..."
if ! git fetch --quiet origin 2>/tmp/wtp-fetch-error; then
  echo "git could not reach GitHub:"
  head -2 /tmp/wtp-fetch-error | sed 's/^/  /'
  echo
  echo "Trying plain HTTPS instead..."
  run_https_update
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

# ------------------------------------------------------------------- apply

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
rm -f "$VERSION_FILE"        # git is authoritative again

post_update
