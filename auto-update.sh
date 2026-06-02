#!/bin/bash
# Auto-update Watchy from GitHub — called by systemd timer every 5 min.
set -e

REPO_DIR="/home/watchy/watchy"
cd "$REPO_DIR"

git fetch origin main 2>&1 || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') New commits found, pulling..."
    git pull origin main
    systemctl restart watchy
    echo "Watchy restarted."
else
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') Already up to date."
fi
