---
name: watchy-vps-migration
description: VPS 迁移已完成结案 — Hetzner 老机已删/停计费,Watchy 单机稳定运行在搬瓦工 LA qcvps
metadata: 
  node_type: memory
  type: project
  originSessionId: d502b99b-6e92-47d6-acaf-29cde30823cf
---

- **🆕 2026-07-11 别被 systemd 的内存数吓到（实测厘清）**：`systemctl status watchy` 报的 `Memory` 是**整个 cgroup 求和**，稳态 ≈ **700–720 MB** = 主 daemon(~550 MB) + **一个常驻子 worker 进程**(~150 MB)。子 worker 是主进程 fork 的（`pstree -p <MainPID>` 里挂在主进程下、`ps -o ppid` 显示 PPID=主 daemon），**不是孤儿/泄漏，正常，别去 kill 或重启回收**。单看主进程 RSS 仍是 ~460–550 MB 基线。本条以下所有「稳态常驻 ~460–510MB」指的都是**单主进程 RSS**，不是 systemd cgroup 数——多租户余量测算按 cgroup ~700 MB 起算才准。当时 `free -m`：available 1 GB、swap 只用 39 MB，健康无压力。判 systemd 数值异常前先 `ps -o pid,ppid,rss --ppid <MainPID>` 拆父子进程。

- **🏁 2026-06-24 迁移正式结案。** 新机(qcvps)已**跑通至少一次完整 Tier-2 批次,Schwab/LLM/Telegram 全链路 OK**(用户确认)→ decommission gate 满足。**老机(Hetzner)已 `server delete`**;Hetzner Cloud 按小时计费、删实例即停止扣费,无预付年费要退 → 彻底退租完成。Watchy 现单机运行在搬瓦工 LA `qcvps`(`65.49.218.116`,Ubuntu 24.04,3 vCPU/2GB/2GB swap)。下方为迁移过程历史记录,保留备查;遗留待办见本条末尾。
  - **剩余待办(非阻塞,环境增强)**：~~① Cloudflare Tunnel SSH~~ **✅ 2026-06-29 完成**：tunnel `qcvps-ssh` → `fps.cong.fyi`(zone cong.fyi)，过机场全程可连，8022 hack 退役；另加 fail2ban；未上 Access(免费版要 billing，风险可接受)。细节见 [[ssh-airport-port-block]]。~~② VPS 上装 Claude Code~~ **✅ 已弄(2026-06-29 用户确认)**。~~④ Schwab token 重新 OAuth~~ **✅ 已弄(2026-06-29 用户确认)**——注意这是 ≤7 天周期运维不是一次性，照常 `scripts/schwab_oauth.py --force`。③ 多租户栈 Docker+CouchDB(Obsidian LiveSync)+cloudflared —— **用户 2026-06-29 说「之后再说，可能这个 task 就删掉了」→ 搁置/可能不做**；真上的话 2GB 机叠 Watchy 稳态常驻 ~460–510MB 余量偏紧要盯 swap，且 cloudflared 已就位(SSH tunnel)可复用加 ingress。

- **✅✅ 2026-06-23 迁移已执行（核心完成）**：迁到**新搬瓦工 LA 机**（IP `65.49.218.116`，hostname `qcvps`，Ubuntu **24.04 LTS**，**3 vCPU / 2GB / 2GB swap 装机自带** / 37GB 盘）。**单 `watchy` 用户**（登录+sudo+跑 daemon，复刻老机；放弃了双用户 qc/watchy 方案）。SSH：**专用 key `~/.ssh/qcvps`**（本地 WSL）+ config 别名 `qcvps` + **已关密码登录**（`/etc/ssh/sshd_config.d/00-hardening.conf`：PasswordAuth/KbdInt/PermitRoot 全 no；`00-` 前缀压过 cloud-init 的 50-）；**新机走标准 22 直连(VPN关通)，不复刻老机 8022 hack**，过 VPN 留给 Cloudflare Tunnel（待做）。环境复刻：pyenv+**3.11.9**+`trading` venv → `pip install -r`（老机 `pip freeze` 去掉两个 `-e`，115 钉死依赖）→ `pip install -e TradingAgents@04f434e --no-deps`（+回贴老机 `M main.py` 有意改动 patch）+ `pip install -e watchy@f906a5c --no-deps` → 补 `setuptools>=80.9.0`（freeze 没带）。数据 server→server 经笔记本中转（~1.3MB）：`state.db`、`watchy_config/`（secrets/positions/positions_cache/schwab_tokens.db）。**Schwab token 直接搬 db（6/22 的，新鲜）→ 暂未重新 OAuth**。systemd 三件套 + sudoers drop-in（`watchy NOPASSWD: /usr/bin/systemctl restart watchy`，visudo -c 过）已装。验证：**pytest 284 passed**（VPS 本来没 pytest，临时装；排除 test_e2e）+ config 加载 OK。切换：停老机 daemon+timer（已 disable）→ 起新机 → **active，22 jobs，无 traceback，内存 93M idle**。**待办**：① 11:30 UTC Tier-2 跑通做端到端实证（Schwab/LLM/Telegram）② Cloudflare Tunnel SSH ③ 装 Claude Code ④ watchy 现已**公开**库(HTTPS clone，免 key；以后 Claude Code push memory 才需 GitHub 写权限) ⑤ **老机先停着别删，观察 1-2 天再 decommission**（赶 2026-07-02 续费前）。clone 时 GitHub host-key 变是因重装，正常。
- **（历史背景，下方决策已被 06-23 执行取代）** 是否把 Watchy 从当前 VPS（3核4G，overkill，**2026-07-02 bill**）降配到 **搬瓦工 LA `USCA_2`**（20GB / 1GB / 2× CPU / $50/年）。**未定，用户主动跟进**；**决策输入 = 实测 Tier-2 RAM 峰值**，2026-07-02 续费前决定：峰值在 1GB 上留足余量就换（省钱），跑得紧就续当前机。

- **🆕 2026-06-14 转折：VPS 要变多租户，1GB 降配基本不推荐了。** 用户计划在 VPS 上跑 **Docker Engine + docker compose + CouchDB 容器（Obsidian LiveSync）+ Cloudflare Tunnel（cloudflared）**，外加*可能*的网页后端（域名怎么用还没定，GitHub Pages 不够才上 VPS）。已知新增基线 = Docker(~70–100MB) + CouchDB(~100–150MB，compaction 会冲高) + cloudflared(~30–50MB) ≈ **+200–300MB**（还没算网页后端）。叠在 Watchy Tier-2 峰值（周日 459MB，工作日未测）上，**1GB 机在每日批次窗口很可能吃 swap**——而 swap 伤的是交互型租户（LiveSync 同步、网页），不是批处理 daemon。**临时结论：1GB 降配从「推荐」变「勉强/不推荐」→ 留 4G，或选 ~2G 档。** 加分项：Cloudflare Tunnel 只出站、无入站口（安全），还能**承载 SSH、干掉 8022 机场端口 hack**（见 [[ssh-airport-port-block]]）。CouchDB 别裸奔公网（绑 localhost，只经 tunnel + Cloudflare Access 暴露）。Watchy 跑在 host（systemd），新栈容器化 → 别把 `~/watchy_config` bind-mount 进任何容器。磁盘 20GB 装 Docker 镜像会紧，留意。

- **⏳ RAM 峰值 open thread（决定降不降配）：**
  - **已测**：`watchy.service` **idle 基线 = 150MB**（MemoryPeak，CPU 3.17s），18h uptime（自 2026-06-13 09:31 UTC）。⚠️ **该窗口没跑过 Tier 2**——周六(06-13)跳过 + 周末（Tier 1 受市场时段门控）→ 没跑 propagate。150MB 只是 idle 基线，**不是 Tier-2 峰值**（我一开始误判说涵盖了，已纠正）。
  - **本地代理交叉验证**（Windows/py3.13）：整套 import 栈 ≈ **205MB RSS**；内存由 import 主导，行情数据可忽略（17票 +2.5MB）；Linux/py3.11 更低，与 live 150MB 一致。
  - **✅ 已测 2026-06-14（周日 3-way risk-debate Tier 2）**：`MemoryPeak = 461 MiB`（483,819,520 B；批次中 459 → 跑完 461）。周末单 pipeline、无并发，不是绝对峰值。⚠️ **是在 STALE 代码上测的**（见下面 auto-update bug，daemon 还是 06-13 的；RAM 仍有代表性，但活的 watchlist 可能让真峰值再高点）。
  - **🔑 关键发现：跑完批次后内存不回落到 150MB idle 基线。** 批次 11:30 结束、13:37（2h 后）读 `MemoryCurrent` 仍 **461MiB**（≈峰值）。CPython 不把释放的 arena 还给 OS，所以**稳态常驻 ≈ 460+MB，不是 150**。当初 150「idle」是**第一次批次前/刚重启**才有的假象。**这推翻了「459<500 → 1GB 够用」的结论**：稳态 Watchy 常驻 ~460–500MB，多租户机再叠 Docker+CouchDB+cloudflared ≈ +250MB → 还没算峰值/网页就 ~710–750MB 常驻 → **1GB 不行，留 4G 或上 ~2G。**（观察几天：无重启时 MemoryPeak 若每天涨就是泄漏，不只是 arena 滞留；现在修好的自动重启会掩盖它。）
  - **🐞 2026-06-14 auto-update 静默失败 bug（已修+已部署 a5331a3）**：`auto-update.sh` 以 `User=watchy` 跑，`systemctl restart watchy` 重启系统单元需 root → git pull 成功但 restart 静默失败（set -e 在成功 pull 后中止），daemon 跑 STALE 代码约 1 天（disk 在 9ffe27d，进程还是 06-13 启动的）。修法：`sudo systemctl restart watchy` + 新建 `/etc/sudoers.d/watchy-autoupdate`（`watchy NOPASSWD: /usr/bin/systemctl restart watchy`，0440）+ `git pull --ff-only` 脏树大声失败 + 去掉 set -e 改显式报错。**已部署**：sudoers 建好，13:53 UTC 重启到当前代码（TOKENCOST + 活 watchlist 生效）。注意 VPS 上 `auto-update.sh` 有个老的 `chmod +x` mode-diff，得先 `git checkout --` 丢弃才能拉取脚本更新。**换新 VPS 必须重建这个 sudoers drop-in**（详见 repo CLAUDE.md systemd 抓取项 #6）。**副作用**：现在每次 push 都会重启 daemon → 别在 Tier-2 窗口（~11:30–13:00 UTC）push，会打断批次。
  - **✅ 已测 2026-06-16（工作日 `risk0` 批，4 analysts，活 watchlist）**：`MemoryPeak ≈ 513.5 MB`。**比周日 461MiB 还高**（工作日 Tier-1 触发的 pipeline 叠在还没跑完的 Tier-2 批次上 → 并发更高）。**坐实 1GB 出局**：稳态常驻 ~460–510MB（不回落）+ 多租户 Docker/CouchDB/cloudflared ~+250MB → ~760–810MB 常驻还没算余量 → **留 4G 或上 ~2G。** 工作日峰值 open thread 已闭。
  - **（历史 open thread，已被上面闭掉）**工作日 11:30 UTC 形态不同（4 analysts）+ 17 票串行批次可能跑过 13:30 UTC（美股开盘）→ Tier-1 pipeline 叠 Tier-2 批次。读法：`systemctl show watchy -p MemoryPeak -p MemoryCurrent`（别重启否则高水位清零）；sysstat 默认10min，细看 `sar -r 30 180`。
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
