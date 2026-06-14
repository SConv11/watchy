#!/bin/bash
# Auto-update Watchy from GitHub — called by systemd timer every 5 min.
# Runs as User=watchy. Restart of the system unit needs root, granted via
# /etc/sudoers.d/watchy-autoupdate (watchy NOPASSWD: systemctl restart watchy).
REPO_DIR="/home/watchy/watchy"
cd "$REPO_DIR" || exit 1

git fetch origin main 2>&1 || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') Already up to date."
    exit 0
fi

echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') New commits found, pulling..."
if ! git pull --ff-only origin main; then
    # Most likely a dirty working tree (e.g. a local config.yaml edit) or a
    # non-fast-forward. Fail loudly and do NOT restart onto a half-applied state.
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') ERROR: git pull --ff-only failed (dirty tree / non-ff?) — NOT restarting." >&2
    exit 1
fi

if sudo systemctl restart watchy; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') Watchy restarted onto $(git rev-parse --short HEAD)."
else
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') ERROR: restart failed — daemon may be running STALE code." >&2
    exit 1
fi
