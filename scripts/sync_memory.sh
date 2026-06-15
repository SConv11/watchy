#!/usr/bin/env bash
# Mirror Claude Code's per-machine memory dir into the repo so it travels via git
# (the ~/.claude memory store is per-machine, keyed by the project's absolute path,
# and does NOT sync across machines on its own).
#
# Registered as a SessionEnd hook. The memory source path is machine-specific, so
# the hook lives in .claude/settings.local.json (git-ignored, per-machine) and
# passes the source dir as $1, e.g.:
#   bash scripts/sync_memory.sh "C:/Users/qc/.claude/projects/C--Users-qc-watchy/memory"
#
# Other machine: add the same SessionEnd hook to ITS settings.local.json with ITS
# own memory path. See .claude/memory/watchy-memory-sync.md.
set -uo pipefail

SRC="${1:-}"
[ -n "$SRC" ] && [ -d "$SRC" ] || exit 0

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
DEST="$REPO/.claude/memory"
mkdir -p "$DEST"

# Mirror source -> dest (clear first so deletions propagate).
rm -f "$DEST"/*.md
cp "$SRC"/*.md "$DEST"/ 2>/dev/null || true

cd "$REPO" || exit 0
git add .claude/memory
# Commit ONLY the memory pathspec — never sweep up unrelated staged work.
git diff --cached --quiet -- .claude/memory && exit 0
git commit -q -m "chore(memory): auto-sync Claude memory" \
  -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" -- .claude/memory
git push -q 2>/dev/null || true
exit 0
