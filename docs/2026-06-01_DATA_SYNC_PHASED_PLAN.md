# 数据同步分阶段实施计划

> 本文档定义从本地 pipeline 产物到服务器服务可用之间的数据通路，按三阶段递进式落地。

---

## 当前阻塞项

**SSH 通道未确认**：服务器至本机的免密登录、防火墙连通性、`/opt/hermass/` 目录权限均未验证。必须先确认通道可用才能进入阶段 1.2。

---

## 阶段 1：本地闭环验证

**时间线**：当前 → 即日可用  
**目标**：pipeline 成功运行后，能在本地验证输出完整性，不依赖网络传输出。

### 1.1 pipeline 成功判定（已实现）

`scripts/run_daily_pipeline.sh` 末尾执行以下动作：

1. **目录级校验**：对 `p116_foundation_${YMD}` 目录执行存在性 + 空目录判断
2. **文件级校验**：`daily_snapshot.json` 存在且非空
3. **DB 文件最小大小**：`p116_foundation.duckdb` > 1KB
4. **标记文件**：写入 `outputs/.pipeline_markers/pipeline_success_${YMD}`，内容为 `${DATE_STR} ${H:M:S}`

### 1.2 非关键目录观察

以下目录若不存在不计入失败，但会记录 `[SKIP]` 日志：

```text
outputs/strategy_signals/
outputs/unified_view/
outputs/market_phase/
outputs/industry_rotation/
```

### 1.3 同步脚本（已实现）

`scripts/sync_outputs_to_server.sh` 由 pipeline Step 10 调用，按以下顺序同步：

```text
1.  Foundation DB → root@8.130.125.201:/opt/hermass/outputs/p116_foundation_${YMD}/
2.  每日快照   → /opt/hermass/outputs/daily_snapshot.json
3.  策略信号   → /opt/hermass/outputs/strategy_signals/
4.  统一视图   → /opt/hermass/outputs/unified_view/
```

退出码语义：
- `0`：全部同步成功
- `2`：部分目标失败（非关键目录），流水线继续
- 其他：严重失败，需要人工介入

### 1.4 阻塞工作项

| 项 | 状态 | 前置条件 |
|----|------|----------|
| SSH 免密登录测试 | TODO | 服务器 IP 可达，`/root/.ssh/authorized_keys` 包含本机公钥 |
| 服务器目录创建 | TODO | SSH 连通后 `mkdir -p /opt/hermass/outputs` |
| 端到端 dry-run | TODO | 完成前两项后手动跑一次 `bash scripts/run_daily_pipeline.sh <昨日日期>` |

---

## 阶段 2：通道评估矩阵

**时间线**：阶段 1 完成后选择  
**目标**：确定长期数据传输方案。

### 评估标准

| 维度 | 权重 | 说明 |
|------|------|------|
| 可靠性 | 高 | 断点续传、失败重试、幂等性 |
| 带宽 | 中 | 每日约 50-200MB（视 p116_foundation 大小） |
| 安全性 | 高 | 需覆盖凭证不落地 |
| 运维成本 | 低 | 服务器无额外依赖 |

### 候选方案

| 方案 | 适用条件 | 风险等级 | 备注 |
|------|----------|----------|------|
| **SSH rsync（当前）** | 本机与服务器同 VPN，ping < 50ms，SSH 稳定 | 低 | 已验证工具链，但依赖本机 pipeline 跑完 |
| **SSH sftp 批量** | 同上，但需原子性 | 低 | 实现简单，但无原子 rename |
| **HTTPS 推送网关** | 服务器对外有域名+证书 | 中 | 需在服务器部署接收服务，增加攻击面 |
| **人工拷贝（U盘/网盘）** | 无网络通道 | 高（人为错误） | 仅应急 |
| **Git LFS** | 产物可入库 | 中 | 仓库膨胀，非数据备份场景 |
| **对象存储（OSS/S3）** | 有云账户 | 低（已解决通道） | 引入新服务，需付费 |

### 推荐后续

阶段 2 正式开启前，需要：
1. 实测阶段 1 dry-run 的 rsync 传输时间和成功率
2. 确认服务器是否有裸域名/IP 可暴露 HTTPS 服务
3. 评估是否需要"server 侧 pull"（服务器 SSH 回拉本机）vs"本机 push"（本机 rsync 到服务器）

---

## 阶段 3：原子同步模板（未来）

**时间线**：阶段 2 选定后设计  
**目标**：建立 server-atomic 写入保障，防止消费者读到半成品。

### 3.1 模板流程（不绑定具体工具）

```
本机产出
  → 写入 incoming/<date>/
  → checksum 校验通过
  → mv incoming/<date>/ → live/<date>/
  → 写标记文件 live/.marker_<date>
  → server 侧消费进程扫描 marker → 加载
```

### 3.2 设计约束

- 写入方不许直接覆盖 `live/`
- 消费方只读取 `live/.marker_*` 列表，跳过 `incoming/`
- 每个日期目录对应一个 marker 文件
- 使用 `mv`（原子 rename）而非复制

### 3.3 扩展方向

- **定时 poll**：服务侧定时扫描 marker（已支持 `pipeline_daemon.py`）
- **webhook**：pipeline 完成时通知 server（扩展时引入）
- **校验链**：多文件联合 hash 文件，防止只传了部分文件

---

## 目录命名约定

| 内容 | 本地路径 | 服务器路径 |
|------|----------|-----------|
| Foundation DB | `outputs/p116_foundation_${YMD}/` | `/opt/hermass/outputs/p116_foundation_${YMD}/` |
| 每日快照 | `outputs/daily_snapshot.json` | `/opt/hermass/outputs/daily_snapshot.json` |
| 策略信号 | `outputs/strategy_signals/` | `/opt/hermass/outputs/strategy_signals/` |
| 统一视图 | `outputs/unified_view/` | `/opt/hermass/outputs/unified_view/` |
| Pipeline 标记 | `outputs/.pipeline_markers/pipeline_success_${YMD}` | 不传（仅本地校验用） |

---

## 路由说明

- 阶段 1 产物：本文件 + `scripts/run_daily_pipeline.sh` + `scripts/sync_outputs_to_server.sh`
- 阶段 2 产物：`docs/2026-06-02_CHANNEL_SELECTION.md`（待选）
- 阶段 3 产物：`docs/CHANNEL_SELECTION.md`（待选）

---

## 附录：当前 log 输出示例

```text
[2026-06-01 15:30:00] Step 10/10: 同步数据到服务器...
[lint-sync] 同步中...
[lint-sync] 数据同步完成
[2026-06-01 15:30:12] Step 11: 输出校验...
[2026-06-01 15:30:12]   [OK] Foundation DB: ...
[2026-06-01 15:30:12]   [OK] Foundation DuckDB: ...
[2026-06-01 15:30:12]   [OK] 每日快照: ...
[2026-06-01 15:30:12]   [SKIP] strategy_signals: 目录不存在或为空
[2026-06-01 15:30:12] 校验通过，标记文件已写入: ...
[2026-06-01 15:30:12] 流水线完成 - 2026-06-01
[2026-06-01 15:30:12] 状态: SUCCESS
```
