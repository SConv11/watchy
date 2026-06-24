---
name: watchy-journald-persistence
description: VPS journald 持久化配置（换机必做）——保住 TOKENCOST/门控日志用于成本对账
metadata: 
  node_type: memory
  type: project
  originSessionId: 91567a28-ac96-409d-b21a-560b93bf0b3b
---

# Watchy VPS journald 持久化（换机必做）

**背景：** 2026-06-24 迁到新 VPS `qcvps` 后发现 journal 是全新的，6/23 之前的日志随老 Hetzner 机删掉、找不回（见 [[watchy-vps-migration]]）。成本对账要靠 VPS 上的 `TOKENCOST` 行和 `Tier 2 skip` 行（见 [[watchy-api-cost-baseline]]），所以 journal 不能丢。

**修法（drop-in，需 sudo）：**

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/watchy.conf >/dev/null <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=2G
MaxRetentionSec=180day
EOF
sudo systemctl restart systemd-journald
```

- `Storage=persistent` → 落盘 `/var/log/journal`（默认 `auto` 易丢早期日志）。
- `SystemMaxUse=2G` → 磁盘有几十 G（2G 是**内存**不是磁盘），2G 上限毫无压力；`log_level: DEBUG` 比较啰嗦，盖子防爆盘。
- `MaxRetentionSec=180day` → 半年留存，跨季度对账够。
- journald 另有默认保护：单 fs 最多用 10%；2G 显式上限说了算。

**验证：** `cat /etc/systemd/journald.conf.d/watchy.conf` + `journalctl --disk-usage`（配好当天才 32M，慢慢攒）。

**已配机器：** `qcvps`（2026-06-24）。换新机照搬这段。
