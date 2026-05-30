# 策略绩效归因框架验证报告

版本：v1.0  
日期：2026-05-23  
状态：归因演练 — 基于 2026-05-22 实际数据  
案例标的：300969.SZ 恒帅股份

---

## 1. 案例选取说明

### 1.1 选取标准

用户要求优先选取命中"收缩后释放"路径的 VCP 信号。经扫描 2026-05-22 全部 50 个 VCP 信号，**无任何信号满足 `path_match=true`**。所有 VCP 信号的 `path_rule` 均为 "D1近20日收缩后释放"，但 `path_match` 全部为 `false`/`not_path_match`。

原因：D1 收缩退出时间均超过 20 天阈值。典型值：
- 300969.SZ：d1_days_since_contraction_exit = 27
- 300136.SZ：d1_days_since_contraction_exit = 34
- 688625.SH：d1_days_since_contraction_exit = 32

### 1.2 最终案例

选取 **300969.SZ 恒帅股份** 作为案例，理由：
- VCP 信号中综合质量最高（evidence_score=76.75，排名第 4）
- 唯一一个 `strategy_environment_fit=最佳适配` 的 VCP 信号
- `lifecycle_stage=新生`，三周期共振新近形成（all_three_ef_duration=2 天）
- `signal_strength=0.95`，为当日 VCP 信号最高
- 基本面质量健康（quality_score=97.15）

---

## 2. 案例基础信息

| 字段 | 值 |
|------|-----|
| 股票代码 | 300969.SZ |
| 股票名称 | 恒帅股份 |
| 信号日期 | 2026-05-22 |
| 策略 | VCP突破确认 (vcp_breakout) |
| 信号强度 | 0.95 |
| 生命周期 | 新生 |
| 适配度 | 最佳适配 |
| 证据得分 | 76.75 (Tier B, 排名 4) |
| D1 收盘价 | 168.67 |
| 研究属性 | research_only=true |

---

## 3. 五维归因逐维分析

### 3.1 维度一：State 环境

#### 原始数据

| 特征 | 值 |
|------|-----|
| MN1 State | E (score=14) |
| W1 State | E (score=14) |
| W1 状态转换 | C -> E（transition 标签） |
| D1 State | E (score=14) |
| State Score Sum | 42 |
| EF Count | 3 |
| MN1 EF 持续 | 7 天 |
| W1 EF 持续 | 2 天 |
| D1 EF 持续 | 5 天 |
| 三周期共振持续 | 2 天 |
| D1 前次收缩持续 | 24 天 |
| D1 距收缩退出 | 27 天 |

#### 特征编码（按框架规范）

```python
state_features = {
    "ef_count": 3,                          # 直接使用
    "fit_score": 100,                       # 最佳适配 = 100
    "lifecycle_stage_encoded": 1,           # 新生 = 1
    "state_combo_type": 3,                  # E/E/E 全 E = 已验证组合
    "d1_ef_duration": log(1+5)/log(1+60) = 0.306,
    "d1_volatility_bit": 0,                 # volatility_ratio=0.0
}
```

#### 归因判断

| 检查项 | 结果 | 说明 |
|--------|------|------|
| EF Count = 3 | 有利 | 三周期全 E/F，State 环境极佳 |
| 适配度 = 最佳适配 | 有利 | 框架最高等级 |
| 生命周期 = 新生 | 有利 | VCP 在新生阶段表现最佳 |
| 三周期共振新近形成(2天) | 有利 | 刚进入共振，动能充沛 |
| W1:C->E 转换 | 有利 | 周线刚从收缩进入扩张 |
| D1 距收缩退出 27 天 | 中性偏不利 | 超过 20 天路径阈值，path_match=false |

**贡献方向：positive**（State 环境整体有利，唯一瑕疵是 D1 收缩退出时间略久）

**可归因性：可以归因** — 所有 State 特征数据完整，来自 state_cache 和 strategy_reminders。

---

### 3.2 维度二：市场阶段

#### 原始数据

| 特征 | 值 |
|------|-----|
| 全市场三周期 E/F 数量 | 223 只（较上日 +58）|
| 市场阶段判定 | 趋势新生（emergence）|
| 创业板指 20 日收益 | +6.77% |
| 中证1000 20 日收益 | +4.09% |
| 沪深300 20 日收益 | +1.62% |
| 券商 ETF 20 日收益 | -2.72% |
| 半导体 ETF 20 日收益 | +33.88% |

#### 宽基指数 State 快照

| 指数 | State Combo | EF Count | Score |
|------|-------------|----------|-------|
| 上证指数 | D/8/-C | 0 | 3.4 |
| 沪深300 | E/A/C | 1 | 6.0 |
| 中证1000 | D/E/C | 1 | 6.0 |
| 中证500 | D/C/C | 0 | 4.0 |
| 深证成指 | C/A/C | 0 | 4.0 |
| 创业板指 | C/A/D | 0 | 4.0 |

#### 特征编码

```python
phase_features = {
    "market_phase_encoded": 1,              # emergence = 1
    "pool_size_normalized": 223/500 = 0.446,
    "pool_change_5d": None,                 # 需历史数据计算
    "volatility_ratio": 0.0,                # 来自 state_lifecycle
}
```

#### 归因判断

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 市场阶段 = emergence | 有利 | VCP 最佳阶段为 emergence/progression |
| E/F 池 223 只，日增 58 | 有利 | 池规模快速扩张，趋势新生确认 |
| 成长风格强（创业板 +6.77%） | 有利 | VCP 偏好成长风格 |
| 小盘相对强（中证1000 +4.09%） | 有利 | 300969 为创业板小盘 |
| 宽基指数 EF Count 普遍低 | 中性 | 仅沪深300/中证1000有1个E，市场分化 |

**贡献方向：positive**（市场处于趋势新生阶段，成长/小盘风格有利）

**可归因性：可以归因** — 市场阶段数据来自 daily_research_brief，pool_size 和风格数据完整。`pool_change_5d` 需历史序列补充。

---

### 3.3 维度三：产业链景气

#### 原始数据

| 特征 | 值 |
|------|-----|
| 申万一级 | 汽车 |
| 申万二级 | 汽车零部件 |
| 申万三级 | 其他汽车零部件 |
| 行业先验得分 | 8.0/10 |
| 行业先验置信度 | 0.75 |
| 行业先验状态 | ok |
| 后验调整方向 | positive |
| ETF 标的 | 515700.SH 新能车ETF |
| ETF State Combo | E/2/F |
| ETF EF Count | 2 |
| 动态事件数 | 0 |
| 产业链位置 | 未标注 |

#### 特征编码

```python
chain_features = {
    "chain_prosperity_normalized": 8.0/10 = 0.8,
    "chain_position_encoded": None,         # 未标注
    "etf_ef_count": 2,
    "market_match_level_encoded": 0,        # not_match = 0
}
```

#### 归因判断

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 行业先验 8.0/10 | 有利 | 汽车产业链景气度高 |
| ETF EF Count = 2 | 有利 | 新能车ETF 处于 E/2/F，行业趋势支持 |
| 后验调整 positive | 有利 | 产业/行业先验支持 |
| 产业链位置未标注 | 缺失 | chain_position = "未标注" |
| MA2560 市场匹配 = not_match | 中性 | VCP 不依赖 MA2560 匹配 |
| 动态事件数 = 0 | 中性 | 无新增产业链事件 |

**贡献方向：positive**（行业景气度高，ETF 共振支持）

**可归因性：部分可归因** — `chain_prosperity` 和 `etf_ef_count` 完整，但 `chain_position` 缺失（未标注）。动态事件数为 0，产业链事件扫描器尚未产生数据。

---

### 3.4 维度四：宏观环境

#### 原始数据

| 特征 | 值 |
|------|-----|
| 宏观先验得分 | 5.0/10 |
| 宏观置信度 | 0.25 |
| 宏观状态 | partial |
| 使用指标数 | 2 |
| 可用指标数 | 13 |
| 需要代码数 | 2 |
| iFinD 错误码 | null（Tushare 部分可用）|

#### 可用宏观证据

- Tushare: 货币供应量 — 有数据但暂无明确方向
- Tushare: 社会融资规模 — 有数据但暂无明确方向

#### 市场风格先验（可用）

| 风格 | 得分 | 标签 |
|------|------|------|
| 风险偏好 | 5.57 | 市场先验中性 |
| 成长风格 | 8.09 | 成长相对强 |
| 小盘风格 | 6.48 | 小盘相对强 |

#### 策略宏观先验

| 特征 | 值 |
|------|-----|
| prior_fit_score | 6.59 |
| confidence | 0.36 |
| logic | VCP 更依赖成长风格、风险偏好和宏观增长/流动性共振 |

#### 特征编码

```python
macro_features = {
    "macro_score_normalized": 5.0/10 = 0.5,
    "quadrant_encoded": None,               # 未判定象限
    "strategy_macro_adj": None,             # 无策略专属加成数据
    "macro_confidence": 0.25,               # 低置信度
}
```

#### 归因判断

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 宏观得分 5.0/10 | 中性 | 中性分数，不参与强化判断 |
| 宏观置信度 0.25 | 不利 | 仅 2/13 指标可用，数据严重不足 |
| 成长风格 8.09 | 有利 | VCP 偏好成长风格，此维度支持 |
| 风险偏好 5.57 | 中性 | 中性水平 |
| 策略宏观适配 6.59 | 中性 | 中等适配，confidence 仅 0.36 |
| 象限未判定 | 缺失 | 无宏观象限数据 |

**贡献方向：neutral**（宏观数据 insufficient，但成长风格有利）

**可归因性：无法完整归因** — 核心缺失：
1. 宏观象限未判定（需要 GDP/CPI/PPI/M2 等完整数据）
2. 仅 2/13 宏观指标可用，iFinD 用量超限问题已部分缓解（Tushare 替补）
3. 策略专属宏观加成无数据

---

### 3.5 维度五：策略自身

#### 原始数据

| 特征 | 值 |
|------|-----|
| 策略 ID | vcp |
| 信号类型 | entry |
| 信号名称 | VCP突破确认 |
| 原始信号 | vcp_breakout |
| 信号强度 | 0.95 |
| 路径规则 | D1近20日收缩后释放 |
| 路径匹配 | false (not_path_match) |
| VCP 近 6 日命中数 | 6 |
| 策略得分 | 105.0 |

#### 因子拆解（来自 factor_breakdown）

| 因子 | 得分 (0-1) | 积分贡献 |
|------|-----------|----------|
| state | 0.75 | 33.75 |
| strategy | 1.0 | 40.0 (signal 30 + persistence 10) |
| pattern | 0.0 | 0.0 |
| transition | 0.375 | 3.0 |
| fundamental | 0.0 | 0.0 |

#### State 生命周期子因子

| 子因子 | 得分 | 说明 |
|--------|------|------|
| expansion_ratio | 1.0 | 扩张充分 |
| trend_ratio | 1.0 | 趋势完整 |
| position_ratio | 1.0 | 位置有利 |
| volatility_stability | 1.0 | 波动稳定 |
| d1_recent_contraction_exit | 0.0 | D1 收缩退出不满足"近20日" |
| d1_prior_contraction_depth | 1.0 | 前次收缩深度充分（24天） |
| w1_recent_contraction_exit | 0.5 | W1 收缩退出部分满足 |

#### 特征编码

```python
signal_features = {
    "signal_type_encoded": 0,               # entry = 0
    "signal_strength": 0.95,
    "path_condition_met": 0,                # false = 0
    "strategy_id_encoded": 0,               # vcp = 0
}
```

#### 归因判断

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 信号强度 0.95 | 有利 | 当日 VCP 最高强度 |
| 策略得分 105 | 有利 | 策略规则触发充分 |
| strategy=1.0 | 有利 | 策略因子满分 |
| path_condition_met=false | 不利 | 未命中"收缩后释放"路径 |
| pattern=0.0 | 不利 | 形态因子零分 |
| d1_recent_contraction_exit=0.0 | 不利 | 核心路径条件未满足 |
| VCP 6 日内命中 6 次 | 中性 | 信号密度高，可能过热 |

**贡献方向：neutral**（信号强度和策略规则有利，但路径条件未满足导致 pattern 零分）

**可归因性：可以归因** — 策略自身数据完整，来自 strategy_evaluation.factor_breakdown。

---

## 4. 归因汇总卡片

```
信号：300969.SZ 恒帅股份 | VCP突破确认 | 2026-05-22
D1 收盘价：168.67
20 日超额收益：pending_future_data（信号当日，需前向观察）

┌─────────────────┬─────────────┬─────────────┬─────────────────────────────┐
│ 维度            │ 贡献方向    │ 可归因性    │ 关键判断                    │
├─────────────────┼─────────────┼─────────────┼─────────────────────────────┤
│ State 环境      │ positive    │ 可以归因    │ 最佳适配+新生+三周期全E     │
│ 市场阶段        │ positive    │ 可以归因    │ emergence阶段，成长/小盘强  │
│ 产业链景气      │ positive    │ 部分可归因  │ 汽车8.0/10，但position缺失  │
│ 宏观环境        │ neutral     │ 无法完整归因│ 仅2/13指标，象限未判定      │
│ 策略自身        │ neutral     │ 可以归因    │ 强度0.95高，但path未命中    │
└─────────────────┴─────────────┴─────────────┴─────────────────────────────┘

主要驱动因子：State 环境（三周期共振新近形成 + 最佳适配）
次要驱动因子：市场阶段（趋势新生，成长风格有利）
主要拖累因子：策略自身路径条件（D1收缩退出27天 > 20天阈值）
残差风险：宏观数据缺失、产业链位置未标注
```

---

## 5. 框架可行性评估

### 5.1 各维度数据完备度

| 维度 | 完备度 | 缺失字段 | 阻塞程度 |
|------|--------|----------|----------|
| State 环境 | 95% | pool_change_5d | 非阻塞 |
| 市场阶段 | 85% | pool_change_5d, volatility_ratio 历史 | 非阻塞 |
| 产业链景气 | 60% | chain_position, dynamic_event | 部分阻塞 |
| 宏观环境 | 30% | quadrant, 11/13 宏观指标, strategy_macro_adj | 阻塞 |
| 策略自身 | 90% | forward_return（需未来数据） | 非阻塞 |

### 5.2 归因计算可行性

**简化归因法（分组对比）**：
- 状态：可行 — 所有分组特征（fit_level, lifecycle, ef_count）数据完整
- 阻塞条件：需要 `forward_excess_return_20d`，当前为 pending
- 当前可做：构建归因卡片，标记各维度贡献方向，待未来收益标签完成后计算归因强度

**回归归因法**：
- 状态：不可行 — 需要至少 100+ 条带标签的历史观测
- 当前 labeled 数据量：0（前向观察账本尚未产生 20 日收益）

### 5.3 关键发现

1. **无路径匹配信号**：当日 50 个 VCP 信号全部未命中"收缩后释放"路径，说明路径规则阈值（20天）可能过严，或市场处于特殊阶段
2. **宏观数据是最大短板**：13 个宏观指标中仅 2 个可用，iFinD 用量限制是根本原因。Tushare 替补已部分缓解
3. **产业链位置未标注**：`chain_position` 和 `industry_climate` 在 ifind.industry 中均为"未标注"，需要补充产业链知识库
4. **factor_breakdown 已内置归因逻辑**：strategy_evaluation.factor_breakdown 实际上已经实现了策略自身的归因拆解（state/strategy/pattern/transition/fundamental），可直接复用

---

## 6. 框架改进建议

### 6.1 短期（1-2 周）

1. **补充宏观数据源**
   - 完成 Tushare 宏观指标接入（M2、社融、PMI 等）
   - 解决 iFinD 用量超限问题（申请额度或降级到备用源）
   - 实现宏观象限自动判定（需要 GDP、CPI、PPI、M2 四指标）

2. **放宽路径规则或增加变体**
   - 当前"D1近20日收缩后释放"过于严格，建议增加：
     - "D1近30日收缩后释放"（宽松版）
     - "W1近10周收缩后释放"（周线版）
   - 记录 path_match 率，用于规则校准

3. **补充产业链位置标注**
   - 基于申万三级行业映射到产业链位置（上游/中游/下游/配套）
   - 建立 `industry_chain_mapping` 静态表

### 6.2 中期（1 个月）

4. **建立前向观察账本**
   - 实现 `build_forward_observation_ledger`，每日记录信号并跟踪 5/10/20 日收益
   - 这是归因分析的数据基础，没有它无法计算归因强度

5. **实现简化归因流水线**
   - 按框架规范实现 `simple_attribution()` 和 `build_attribution_report()`
   - 输出到 `outputs/attribution/attribution_report_{date}.json`

6. **产业链事件扫描器数据接入**
   - 当 chain_event_scanner 产生数据后，`dynamic_event_count` 将从 0 变为实际值
   - 这是产业链维度的关键增强

### 6.3 长期（3 个月）

7. **回归归因模型**
   - 积累 500+ 条 labeled 观测后，启用线性回归归因
   - 估计 β_state, β_phase, β_chain, β_macro, β_signal

8. **归因驱动校准**
   - 将归因强度映射到校准层权重调整
   - 实现 `compute_weight_adjustments()` 和 `detect_attribution_anomalies()`

---

## 7. 附录：完整特征向量

```json
{
  "stock_code": "300969.SZ",
  "signal_date": "2026-05-22",
  "strategy_id": "vcp",
  "signal_type": "entry",
  "signal_strength": 0.95,
  "state_features": {
    "ef_count": 3,
    "fit_score": 100,
    "lifecycle_stage_encoded": 1,
    "state_combo_type": 3,
    "d1_ef_duration": 0.306,
    "d1_volatility_bit": 0
  },
  "phase_features": {
    "market_phase_encoded": 1,
    "pool_size_normalized": 0.446,
    "pool_change_5d": null,
    "volatility_ratio": 0.0
  },
  "chain_features": {
    "chain_prosperity_normalized": 0.8,
    "chain_position_encoded": null,
    "etf_ef_count": 2,
    "market_match_level_encoded": 0
  },
  "macro_features": {
    "macro_score_normalized": 0.5,
    "quadrant_encoded": null,
    "strategy_macro_adj": null,
    "macro_confidence": 0.25
  },
  "signal_features": {
    "signal_type_encoded": 0,
    "signal_strength": 0.95,
    "path_condition_met": 0,
    "strategy_id_encoded": 0
  },
  "attribution": {
    "state": "positive",
    "phase": "positive",
    "chain": "positive",
    "macro": "neutral",
    "signal": "neutral"
  },
  "primary_driver": "state",
  "data_gaps": [
    "pool_change_5d",
    "chain_position",
    "macro_quadrant",
    "strategy_macro_adj",
    "forward_excess_return_20d"
  ],
  "research_only": true
}
```

---

## 8. 结论

**框架设计合理，但当前数据完备度不足以支撑完整的量化归因。**

- 可以立即产出**定性归因卡片**（如本报告所示）
- 可以立即运行**分组对比归因**（需积累前向收益标签）
- **回归归因**需要等待 3-6 个月的数据积累
- **最大阻塞项**：宏观数据（完备度 30%）和产业链位置标注（缺失）
- **最大亮点**：State 环境和策略自身数据质量高，factor_breakdown 已内置精细归因

建议优先解决宏观数据源和产业链位置标注，同时启动前向观察账本积累标签数据。
