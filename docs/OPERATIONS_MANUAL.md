# 系统运维手册

版本：v1.0
日期：2026-05-24
状态：运维文档

---

## 1. 每日运行流程

### 1.1 标准收盘后流水线

```bash
# Step 1: 下载当日数据（收盘后 ~16:00）
python3 scripts/download_daily.py --date 2026-05-24

# Step 2: 构建 State 底座
python3 scripts/build_p116_foundation.py --date 2026-05-24

# Step 3: 生成 State 缓存
python3 scripts/state_cache_builder.py --date 2026-05-24

# Step 4: 生成市场资产 State
python3 scripts/build_market_assets_state.py --date 2026-05-24

# Step 5: 生成行业 ETF 配置
python3 scripts/build_industry_etf_config.py --date 2026-05-24

# Step 6: 构建策略信号账本
python3 scripts/strategy_signal_ledger.py --date 2026-05-24

# Step 7: 构建宏观-产业链先验
python3 scripts/build_macro_chain_prior.py --date 2026-05-24

# Step 8: 构建全三 E/F 池
python3 scripts/run_daily_all_three_ef_workflow.py --date 2026-05-24

# Step 9: 生成策略提醒
python3 scripts/strategy_reminder_brief.py --date 2026-05-24

# Step 10: 生成每日总报
python3 scripts/daily_research_brief.py --date 2026-05-24

# Step 11: 更新前向观察账本
python3 scripts/forward_observation_ledger.py --date 2026-05-24

# Step 12: 检查校准触发
python3 scripts/calibration_trigger.py --date 2026-05-24
```

### 1.2 Agently 一键执行

```bash
python3 agently_adapter/stockpool_daily_runner.py run \
  --date 2026-05-24 \
  --previous-date 2026-05-23 \
  --foundation-db outputs/p116_foundation_20260524/p116_foundation.duckdb
```

### 1.3 执行顺序依赖

```text
download_daily
  → build_p116_foundation
    → state_cache_builder (并行) + build_market_assets_state (并行)
      → strategy_signal_ledger
        → strategy_reminder_brief (并行) + daily_research_brief (并行)
          → forward_observation_ledger
            → calibration_trigger
```

### 1.4 预计耗时

| 步骤 | 预计耗时 | 瓶颈 |
|------|----------|------|
| 下载数据 | 5-15 分钟 | 网络 + API 配额 |
| State 底座 | 3-8 分钟 | CPU 计算 |
| 策略信号 | 2-5 分钟 | 三策略扫描 |
| 宏观先验 | 1-3 分钟 | 数据读取 |
| 提醒+总报 | 1-2 分钟 | HTML 渲染 |
| **总计** | **15-35 分钟** | |

---

## 2. 常见故障排查

### 2.1 DuckDB 锁冲突

**症状**：`IOException: Could not set lock on file` 或 `Conflicting lock`

**原因**：多个进程同时访问同一个 DuckDB 文件

**解决方案**：

```bash
# 检查是否有残留进程
ps aux | grep python3 | grep hermass

# 杀掉残留进程
kill <PID>

# 如果锁文件残留
rm outputs/p116_foundation_*/p116_foundation.duckdb.wal 2>/dev/null
```

**预防**：不要并行运行写同一个 DuckDB 的脚本。

### 2.2 API 配额超限

**症状**：iFinD 返回 `-4318` 错误码（`sorry, your usage of data has exceeded this month`）

**解决方案**：

```bash
# 检查当前配额使用情况
python3 scripts/ifind_usage_stress_test.py --date 2026-05-24

# 降级：使用 AKShare/Tushare 替代
python3 scripts/collect_macro_multisource.py --date 2026-05-24 --source akshare

# 或使用 GUI 离线导入
python3 scripts/build_ifind_macro_db.py --date 2026-05-24 --macro-import-file data/ifind_macro_20260524.xlsx
```

### 2.3 数据缺失

**症状**：`FileNotFoundError` 或 输出 JSON 中 `rows: []`

**排查步骤**：

```bash
# 检查数据文件是否存在
ls -la data/raw/*20260524* 2>/dev/null
ls -la outputs/p116_foundation_20260524/ 2>/dev/null
ls -la outputs/state_cache/state_ef_20260524.json 2>/dev/null

# 检查 Foundation DB 是否有数据
python3 -c "
import duckdb
con = duckdb.connect('outputs/p116_foundation_20260524/p116_foundation.duckdb', read_only=True)
print(con.execute('SELECT COUNT(*) FROM p116_foundation WHERE date = ?', ['2026-05-24']).fetchone())
con.close()
"
```

**常见原因**：
- 黑狼 API 下载失败（网络问题）
- 非交易日（周末/节假日）
- iFinD Excel 未导出

### 2.4 策略信号为空

**症状**：`strategy_signal_daily` 中 `signal_count: 0`

**排查**：

```bash
# 检查 Foundation DB 中 ef_count >= 2 的标的数量
python3 -c "
import duckdb
con = duckdb.connect('outputs/p116_foundation_20260524/p116_foundation.duckdb', read_only=True)
print(con.execute('SELECT COUNT(*) FROM p116_foundation WHERE ef_count >= 2').fetchone())
con.close()
"

# 如果为 0，说明全市场无 E/F 共振标的，信号为空是正常的
```

### 2.5 校准触发失败

**症状**：`calibration_trigger.py` 输出 `should_calibrate: false`

**排查**：

```bash
# 检查三重门状态
python3 scripts/calibration_trigger.py --date 2026-05-28 --dry-run
# 查看 gates 中各门的 passed 状态
```

### 2.6 HTML 页面空白

**症状**：`public/*.html` 打开后内容为空

**排查**：

```bash
# 检查 JSON 产物是否有数据
python3 -c "import json; d=json.load(open('outputs/strategy_reminders/reminder_20260524.json')); print(len(d.get('reminders',[])))"

# 检查 HTML 文件大小
ls -la public/strategy_reminder_20260524.html
```

---

## 3. 备份与恢复

### 3.1 需要备份的数据

| 数据 | 路径 | 重要性 | 备份频率 |
|------|------|--------|----------|
| Foundation DB | `outputs/p116_foundation_*/` | 高 | 每日 |
| 策略信号账本 | `outputs/strategy_signals/` | 高 | 每日 |
| 前向观察账本 | `outputs/forward_observation/` | 高 | 每日 |
| 校准报告 | `outputs/calibration/` | 高 | 按需 |
| 配置文件 | `config/` | 高 | 变更时 |
| 文档 | `docs/` | 中 | 变更时 |
| 原始数据 | `data/raw/` | 低 | 可重下载 |

### 3.2 备份命令

```bash
# 每日备份核心数据
tar -czf backup/hermass_$(date +%Y%m%d).tar.gz \
  outputs/p116_foundation_*/ \
  outputs/strategy_signals/ \
  outputs/forward_observation/ \
  outputs/calibration/ \
  config/ \
  docs/
```

### 3.3 恢复流程

```bash
# 解压备份
tar -xzf backup/hermass_20260524.tar.gz -C /Users/lv111101/Documents/hermass-observer-product/

# 验证恢复
python3 -c "
import duckdb
con = duckdb.connect('outputs/p116_foundation_20260524/p116_foundation.duckdb', read_only=True)
print('Foundation:', con.execute('SELECT COUNT(*) FROM p116_foundation').fetchone())
con.close()
"
```

---

## 4. 新策略接入标准操作流程

### 4.1 步骤清单

```bash
# Step 1: 创建信号模块
vim backtest/strategy_signals/your_strategy.py

# Step 2: 在 SIGNAL_META 中注册
# 编辑 scripts/strategy_signal_ledger.py

# Step 3: 在 strategy_registry.json 中新增条目
vim config/strategy_registry.json

# Step 4: 在 compute_environment_fit() 中注册生命周期映射
# 编辑 scripts/strategy_signal_ledger.py

# Step 5: 创建验证脚本
vim scripts/search_your_strategy_optimal_state.py

# Step 6: 运行验证
python3 scripts/search_your_strategy_optimal_state.py \
  --start-date 2025-06-01 --end-date 2026-05-01 \
  --foundation-db outputs/p116_foundation_20260521/p116_foundation.duckdb

# Step 7: 检查验证结果
cat outputs/project/your_strategy_optimal_state_search.md

# Step 8: 如通过，写入规则文件
vim config/your_strategy_state_match_rule.json

# Step 9: 更新策略定义文档
vim docs/STRATEGY_DEFINITIONS.md

# Step 10: 更新提醒层（如需要）
# 编辑 scripts/strategy_reminder_brief.py

# Step 11: 运行完整流水线验证
python3 agently_adapter/stockpool_daily_runner.py run --date 2026-05-24

# Step 12: 检查禁止词汇
grep -rn "买入\|卖出\|加仓\|推荐" scripts/strategy_reminder_brief.py
```

### 4.2 接入检查清单

```
□ 信号函数在 backtest/strategy_signals/ 中
□ SIGNAL_META 已注册
□ strategy_registry.json 已新增
□ best_stage 已注册
□ REMINDER_ENTRY_STRATEGIES 已更新（如适用）
□ 验证脚本产出报告并通过标准
□ 规则文件已写入（如有固化规则）
□ docs/STRATEGY_DEFINITIONS.md 已更新
□ 禁止词汇扫描通过
□ 完整流水线运行无报错
□ 人工审核签字
```

---

## 5. 版本升级注意事项

### 5.1 Schema 变更

当 DuckDB 表结构发生变化时：

```bash
# 1. 备份现有数据库
cp outputs/industry_chain/industry_chain_evidence.duckdb \
   outputs/industry_chain/industry_chain_evidence_backup.duckdb

# 2. 运行迁移脚本
python3 scripts/migrate_chain_tables_v2.py --date 2026-05-24

# 3. 验证
python3 scripts/migrate_chain_tables_v2.py --date 2026-05-24 --verify-only
```

### 5.2 配置文件变更

```bash
# 变更前备份
cp config/strategy_registry.json config/strategy_registry_backup.json

# 变更后验证
python3 -c "import json; json.load(open('config/strategy_registry.json'))"
```

### 5.3 Python 依赖升级

```bash
# 升级前记录版本
pip freeze > requirements_backup.txt

# 升级
pip install --upgrade duckdb numpy akshare

# 验证
python3 -c "import duckdb; print(duckdb.__version__)"
python3 -c "import numpy; print(numpy.__version__)"
```

### 5.4 State 公式变更

**警告**：State 公式（`p116_core.py`）变更将影响所有下游产物。变更后必须：

1. 重建所有 Foundation DB
2. 重建所有 State 缓存
3. 重新运行所有策略信号
4. 重新运行所有验证脚本
5. 更新专利文档（如有实质变更）

```bash
# 全量重建（耗时较长）
for date in $(seq 2025-06-01 2026-05-24); do
  python3 scripts/build_p116_foundation.py --date $date
  python3 scripts/state_cache_builder.py --date $date
done
```
