---
name: watchy-vps-migration
description: VPS downsize decision (4GB→Bandwagon LA 1GB) — DEFERRED, decide before 2026-07-02 on live Tier-2 RAM peak
metadata: 
  node_type: memory
  type: project
  originSessionId: d502b99b-6e92-47d6-acaf-29cde30823cf
---

是否把 Watchy 从当前 VPS（3核4G，overkill，**2026-07-02 bill**）降配到 **搬瓦工 LA `USCA_2`**（20GB / 1GB / 2× CPU / $50/年）。**未定，用户主动跟进**；**决策输入 = 实测 Tier-2 RAM 峰值**，2026-07-02 续费前决定：峰值在 1GB 上留足余量就换（省钱），跑得紧就续当前机。

- **🆕 2026-06-14 转折：VPS 要变多租户，1GB 降配基本不推荐了。** 用户计划在 VPS 上跑 **Docker Engine + docker compose + CouchDB 容器（Obsidian LiveSync）+ Cloudflare Tunnel（cloudflared）**，外加*可能*的网页后端（域名怎么用还没定，GitHub Pages 不够才上 VPS）。已知新增基线 = Docker(~70–100MB) + CouchDB(~100–150MB，compaction 会冲高) + cloudflared(~30–50MB) ≈ **+200–300MB**（还没算网页后端）。叠在 Watchy Tier-2 峰值（周日 459MB，工作日未测）上，**1GB 机在每日批次窗口很可能吃 swap**——而 swap 伤的是交互型租户（LiveSync 同步、网页），不是批处理 daemon。**临时结论：1GB 降配从「推荐」变「勉强/不推荐」→ 留 4G，或选 ~2G 档。** 加分项：Cloudflare Tunnel 只出站、无入站口（安全），还能**承载 SSH、干掉 8022 机场端口 hack**（见 [[ssh-airport-port-block]]）。CouchDB 别裸奔公网（绑 localhost，只经 tunnel + Cloudflare Access 暴露）。Watchy 跑在 host（systemd），新栈容器化 → 别把 `~/watchy_config` bind-mount 进任何容器。磁盘 20GB 装 Docker 镜像会紧，留意。

- **⏳ RAM 峰值 open thread（决定降不降配）：**
  - **已测**：`watchy.service` **idle 基线 = 150MB**（MemoryPeak，CPU 3.17s），18h uptime（自 2026-06-13 09:31 UTC）。⚠️ **该窗口没跑过 Tier 2**——周六(06-13)跳过 + 周末（Tier 1 受市场时段门控）→ 没跑 propagate。150MB 只是 idle 基线，**不是 Tier-2 峰值**（我一开始误判说涵盖了，已纠正）。
  - **本地代理交叉验证**（Windows/py3.13）：整套 import 栈 ≈ **205MB RSS**；内存由 import 主导，行情数据可忽略（17票 +2.5MB）；Linux/py3.11 更低，与 live 150MB 一致。
  - **✅ 已测 2026-06-14（周日 3-way risk-debate Tier 2）**：`MemoryPeak = 461 MiB`（483,819,520 B；批次中 459 → 跑完 461）。周末单 pipeline、无并发，不是绝对峰值。⚠️ **是在 STALE 代码上测的**（见下面 auto-update bug，daemon 还是 06-13 的；RAM 仍有代表性，但活的 watchlist 可能让真峰值再高点）。
  - **🔑 关键发现：跑完批次后内存不回落到 150MB idle 基线。** 批次 11:30 结束、13:37（2h 后）读 `MemoryCurrent` 仍 **461MiB**（≈峰值）。CPython 不把释放的 arena 还给 OS，所以**稳态常驻 ≈ 460+MB，不是 150**。当初 150「idle」是**第一次批次前/刚重启**才有的假象。**这推翻了「459<500 → 1GB 够用」的结论**：稳态 Watchy 常驻 ~460–500MB，多租户机再叠 Docker+CouchDB+cloudflared ≈ +250MB → 还没算峰值/网页就 ~710–750MB 常驻 → **1GB 不行，留 4G 或上 ~2G。**（观察几天：无重启时 MemoryPeak 若每天涨就是泄漏，不只是 arena 滞留；现在修好的自动重启会掩盖它。）
  - **🐞 2026-06-14 auto-update 静默失败 bug（已修+已部署 a5331a3）**：`auto-update.sh` 以 `User=watchy` 跑，`systemctl restart watchy` 重启系统单元需 root → git pull 成功但 restart 静默失败（set -e 在成功 pull 后中止），daemon 跑 STALE 代码约 1 天（disk 在 9ffe27d，进程还是 06-13 启动的）。修法：`sudo systemctl restart watchy` + 新建 `/etc/sudoers.d/watchy-autoupdate`（`watchy NOPASSWD: /usr/bin/systemctl restart watchy`，0440）+ `git pull --ff-only` 脏树大声失败 + 去掉 set -e 改显式报错。**已部署**：sudoers 建好，13:53 UTC 重启到当前代码（TOKENCOST + 活 watchlist 生效）。注意 VPS 上 `auto-update.sh` 有个老的 `chmod +x` mode-diff，得先 `git checkout --` 丢弃才能拉取脚本更新。**换新 VPS 必须重建这个 sudoers drop-in**（详见 repo CLAUDE.md systemd 抓取项 #6）。**副作用**：现在每次 push 都会重启 daemon → 别在 Tier-2 窗口（~11:30–13:00 UTC）push，会打断批次。
  - **还需测（真正的天花板）**：**工作日 11:30 UTC** —— 形态不同（4 analysts），且 17 票串行批次可能跑过 13:30 UTC（美股开盘，EDT）→ **Tier-1 触发的 pipeline 会叠在还没跑完的 Tier-2 批次上**（pool ≈20）。这种并发今天周末没测到，所以 459MB 是个利好数据但**还不是可证的最大值**。跑完工作日批次后读 `systemctl show watchy -p MemoryPeak -p MemoryCurrent`（别重启服务否则高水位清零）。sysstat 默认10min，细看 `sar -r 30 180`。
  - **决策标准**：idle 150MB；Tier 2 串行（`tier2.py:57`）一次一个 pipeline。1GB（可用≈900MB）减极简 Ubuntu（~100–150MB）：Tier-2 峰值 **<~500MB → 1GB 够用**；逼近 ~700MB 或持续吃 swap → 留大机。1GB 机无论如何加 **1–2GB swap**。**实测数字到了记到 repo CLAUDE.md 顶部那条**。
- **实际迁移时和用户一起做**（用户决定「到时候一起做」），并在那时创建 `docs/VPS_MIGRATION.md` runbook（用户让先别建文档）。
- **必须从旧 VPS 抓取、repo 无法重建的东西**（详单见 repo `CLAUDE.md` 顶部 2026-06-14 段，以那为准）：
  1. **TradingAgents 安装**（不在 requirements/pyproject！独立装在 `~/TradingAgents` 用 `pip install -e .`）—— 路径 + git commit + 安装方式。从零搭最容易漏这个。
  2. `trading` pyenv（Python **3.11.9**）的完整 `pip freeze`（钉死 langchain/deepseek/google-genai 等传递依赖）。
  3. `~/watchy/state.db`（derived_target_price + kv 表里的 Schwab 7天计时）—— 拷过去，否则 8% 门控重新自举、多花几天钱。
  4. `~/watchy_config/`：secrets.yaml / positions.yaml / positions_cache.json / schwab_tokens.db。
  5. `/home/watchy/watchy` 工作树有无**未提交改动**，尤其 config.yaml 的 watchlist（systemd 下 daemon 读 `~/watchy/config.yaml` 这个 repo 副本，unit 不设 WATCHY_CONFIG）。
  6. systemd 三件套（repo 里都有）：watchy.service / watchy-update.service / watchy-update.timer → 拷到 /etc/systemd/system，enable --now service **和** timer。**+ 必建 sudoers drop-in**（见上 auto-update bug）。`sudo visudo -c` 验证。
  7. `secrets.yaml` 之外的环境变量（如 `DEEPSEEK_API_KEY`/Gemini）—— systemd unit 不设，但查旧机 shell/env，以防 TradingAgents 读它们。
  8. `watchy` 系统用户 + home `/home/watchy`；pyenv + Python 3.11.9 + virtualenv `trading`。
- **新机搭建顺序**：建 watchy 用户 → pyenv+3.11.9+trading venv → 装 TradingAgents → clone watchy + `pip install -e` → 还原 watchy_config + state.db → systemd → Schwab 重新 OAuth（`scripts/schwab_oauth.py --force` 签发新 7天 token，比迁 db 省事）→ pytest + smokes。
- SSH 连新机的机场拦截解法见 [[ssh-airport-port-block]]。
- 部署细节见 [[watchy-vps-deployment]]；运维/Schwab 见 [[watchy-issue-plan]]。
