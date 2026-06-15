---
name: watchy-memory-sync
description: How Claude memory syncs across the two machines — committed into the repo at .claude/memory/ via a SessionEnd hook
metadata: 
  node_type: memory
  type: project
  originSessionId: a1e73bf8-6f02-4b49-b5b4-fb1b37ab7cc8
---

Claude Code 的 memory 存在本机 `~/.claude/projects/<path-hash>/memory/`，按项目绝对路径键，**不跨机同步**。为了让另一台机器（也在这个 repo 上干活）也能看到，memory **整目录提交进 repo 的 `.claude/memory/`**，跟着 git 走。

**机制（用户 2026-06-15 选定：Stop/SessionEnd hook 自动拷贝，不用 symlink）：**
- 通用脚本 `scripts/sync_memory.sh`（已提交）：把传入的 memory 源目录镜像到 `<repo>/.claude/memory/`，只 commit 那个 pathspec（不卷入别的暂存改动），best-effort `git push`。
- 注册为 **SessionEnd hook**。源路径是机器相关的，所以 hook 写在 **`.claude/settings.local.json`**（git-ignored，每机一份），把源目录当 `$1` 传：
  ```json
  {"hooks":{"SessionEnd":[{"hooks":[{"type":"command",
    "command":"bash scripts/sync_memory.sh \"C:/Users/qc/.claude/projects/C--Users-qc-watchy/memory\""}]}]}}
  ```
- **本机（C:\Users\qc\watchy）已配。** 另一台机一次性照做：在它的 `.claude/settings.local.json` 加同样的 SessionEnd hook，但路径换成**它自己的** `~/.claude/projects/<它的-path-hash>/memory`（hash = 项目绝对路径里 `:`/`\`/`/` 全换成 `-`）。

**附带：docs-sync 提醒 hook（用户 2026-06-15 选「只提醒」）。** `scripts/docs_reminder.sh` + **committed** `.claude/settings.json` 里的 PostToolUse hook（`if: Bash(git commit*)`）：每次 `git commit` 后，若 HEAD 改了代码（`watchy/*.py` 或 `config.yaml`）却没动 README/CLAUDE.md/docs，就注入一条提醒让我按 CLAUDE.md「Keeping docs in sync」检查文档。**只提醒、不自动写、不自动提交**；对 memory 自动提交和纯 tests 提交不触发。路径无关 → 放 committed settings.json，两台机自动继承（不像 memory hook 那样要每机配）。

**含义：**
- 编辑 memory 照常（写本机 `~/.claude/.../memory/`）；会话结束时 hook 自动镜像进 repo 并提交。
- repo 里存的是**真实 .md 文件**（不是 symlink），另一台 clone 下来就是普通文件，能直接读。
- 它那台机器要让自己的 Claude **自动加载**这些，得自己 pull + 让 hook 反向同步（或一次性把 repo 的 `.claude/memory/*` 拷进它的本机 memory 目录）。git 是真相源。
- CLAUDE.md 已据此**瘦身**：细节都进了各 memory 文件（按需召回，不占每次会话上下文），CLAUDE.md 只留约定/工作流/当前状态指针。
