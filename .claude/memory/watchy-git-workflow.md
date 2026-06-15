---
name: watchy-git-workflow
description: "Cross-machine Git sync workflow for watchy (local + VPS) — pull at start, push at checkpoints"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b5650f24-68b0-4787-b928-29a712a1ef71
---

Watchy is worked on across **two machines (local + VPS)**, kept in sync via Git.

**Why:** both machines must not diverge; Git is the single source of truth.

**How to apply:**
- **Always `git pull` before starting any work session.**
- **Always `git push` when ending a session or hitting a checkpoint.**
- Commit messages briefly describe what changed.
- **Commit the `.claude/` directory** (keeps Claude Code config in sync) — do NOT gitignore it.
- **Never commit `.env` or secrets** (Watchy secrets live in `~/watchy_config/secrets.yaml`,
  outside the repo — keep it that way).
- Session flow: start → `git pull` → work → `git add -A && git commit -m "..."` → `git push` → end.
- **If a `git pull`/merge shows CONFLICTS: STOP and tell the user. Do NOT resolve automatically.**

Branching: the user's workflow commits/pushes directly on `main` for this repo (overrides the
default "branch first" rule). The implementation plan lives at `docs/IMPLEMENTATION_PLAN.md`
(in-repo). See [[watchy-issue-plan]].
