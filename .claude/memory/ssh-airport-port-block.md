---
name: ssh-airport-port-block
description: SSH through airport proxy fails (port 22 blocked) — run sshd on 8022 via CLASSIC sshd (not socket activation); battle-tested
metadata: 
  node_type: memory
  type: reference
  originSessionId: d502b99b-6e92-47d6-acaf-29cde30823cf
---

**🏁 2026-06-29 更新：新机 qcvps 已上 Cloudflare Tunnel SSH，8022 hack 退役，本条降为历史备查。** 现在过机场连 qcvps 走 tunnel（见下方「Cloudflare Tunnel 方案」段），不再需要 8022。下面 8022 经典 sshd 方案保留备查（万一某天没 tunnel 时还能用）。

通过机场/代理节点连 VPS 时，`ping` 通但 `ssh` 被拒（`Connection closed by ... port 22`）。**已在老机 hil-2（Hetzner, Ubuntu 24.04）跑通（2026-06-14）。**

**原因**：代理节点是机场「等级3」（美国节点），**屏蔽 22 端口 + 被动高位口 10001–65535**，但**无条件放行主动端口 1024–9999**；ICMP 不走 TCP 拦截所以 ping 通。→ 把 sshd 跑在 1024–9999 内（用 **8022**）。

**⚠️ 大坑：Ubuntu 22.10+/24.04 用 socket activation（`ssh.socket`）**。改 `sshd_config` 的 `Port` 没用（端口归 socket 管）；而且 socket 路子对第二个端口不可靠——`systemctl edit ssh.socket` 加裸 `ListenStream=22/8022` 会让多出来的端口「closed」（单个 `sshd -D` 不 serve 多余 fd），还把 **IPv4 监听弄丢** → **两个端口的 IPv4 都 refused，差点锁死**（靠 Hetzner 网页 console 救回）。**别走 socket 路子。**

**✅ 正确做法 = 关掉 socket activation，用经典 sshd**（改之前留好 22 端口 + 开着带外 console 兜底）：
```bash
printf 'Port 22\nPort 8022\n' | sudo tee /etc/ssh/sshd_config.d/port.conf
sudo sshd -t                              # 校验配置
sudo systemctl disable --now ssh.socket
sudo systemctl enable --now ssh.service
sudo systemctl restart ssh.service        # 必须显式 restart；enable --now 不会重启已运行的服务（踩过：ss 只见 22）
sudo sshd -T | grep -i '^port'            # 应见 port 22 + port 8022
ss -tlnp | grep -E ':22|:8022'            # 应见两端口的 0.0.0.0 + [::]，owner=sshd
sudo ufw allow 8022/tcp                    # ufw 开着的话
```
**按序验证**（逐个排除变量）：① VPS 上 loopback `ssh -p 8022 -l watchy 127.0.0.1`（出 host-key 提示=sshd 在 serve 8022）→ ② 笔记本**关代理** `ssh -p 8022 -l watchy <IP>`（验 IPv4/ufw）→ ③ 笔记本**开代理**（目标：机场放行 8022）。

**坑**：用 `-l watchy` 别用 `watchy@host`——`@` 前多一个空格 ssh 会把用户名当主机名（报错里出现代理 fake-ip `198.18.0.0/15` = 连到代理虚构 IP 了，没到服务器）。

**保留 22 端口**当直连兜底（机场本来就挡 22，无暴露风险）。**锁死了用带外 console 救**：hil-2 用 Hetzner Cloud Console；新 LA 机用 **Bandwagon KiwiVM**（搬瓦工**没有云安全组**，只有系统防火墙）。

**方案 B（不改 VPS）**：域名解析到 IP，`ssh user@vps.yourdomain.com`——机场放行带域名的请求。

## Cloudflare Tunnel 方案（qcvps 现行，2026-06-29 落地，替代 8022）

**只出站、无入站口（443 QUIC），过机场/VPN 全程都能连。** zone `cong.fyi` 已在 Cloudflare 托管。
- **VPS 侧**：`apt install cloudflared` → `cloudflared tunnel login`（打印 URL，本地浏览器选 zone 授权）→ `cloudflared tunnel create qcvps-ssh`（tunnel id `9458906a-eb99-4ad6-b24d-a754cb803529`）→ `cloudflared tunnel route dns qcvps-ssh fps.cong.fyi`（自动建 CNAME）→ `/etc/cloudflared/config.yml` ingress `fps.cong.fyi → ssh://localhost:22`（凭据 json 拷到 `/root/.cloudflared/`，service 以 root 跑）→ `cloudflared service install` + `systemctl enable --now cloudflared`。日志见 `Registered tunnel connection ... location=lax`。ICMP proxy 那两条 WRN 无害（没 ping 权限，跟 SSH 无关）。
- **本地侧**：装 cloudflared（国内 DNS 全挂时直接从 GitHub release 下 `cloudflared-linux-amd64.deb` `dpkg -i`，绕开 `pkg.cloudflare.com`）→ `~/.ssh/config` 别名 `qcvps-cf`：`HostName fps.cong.fyi` + `User watchy` + `IdentityFile ~/.ssh/qcvps` + `ProxyCommand cloudflared access ssh --hostname %h` → `ssh qcvps-cf`。
- **没上 Cloudflare Access**（免费版要绑 billing，用户不想）：风险可接受 —— 裸 IP `65.49.218.116:22` 本来就公网暴露，tunnel 没新增攻击面；真正护城河是 key-only（`00-hardening.conf` 密码登录已全关）。额外加了 **fail2ban**（VPS 侧，`jail.local` 必须 `backend=systemd`，否则 Ubuntu24.04 读不到 journald 日志；经 tunnel 进来源 IP=127.0.0.1 天然在 ignore 列表，不会自封）。
- **三条进出路**：tunnel（机场开）+ 裸 22 直连（机场关，兜底）+ 搬瓦工 KiwiVM console（终极，无云安全组）。
- runbook 用户不让进 repo，只留这条记忆。

相关：Watchy VPS 迁移/降配 [[watchy-vps-migration]]。
