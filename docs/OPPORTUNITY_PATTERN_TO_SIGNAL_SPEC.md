# 机会模式到交易信号的转化规范

版本：v1.0
日期：2026-05-24
状态：设计稿
关联框架：`docs/DATA_DRIVEN_PATTERN_MINING_FRAMEWORK.md`
关联共振：`docs/TRIPLE_RESONANCE_ENHANCEMENT.md`

---

## 核心定位

模式是**统计发现**，策略是**入场规则**。模式不替代策略，只做增强。

```text
模式回答："D1 从收缩跃迁到强势突破时，历史上超额收益如何？"
策略回答："VCP 的 Pivot Point 突破条件是否满足？"
增强回答："VCP 信号恰好出现在已验证模式中 → 信号可信度 +10%"
```

---

## 1. 模式分级与准入标准

### 1.1 三级分级

| 级别 | 代号 | 准入条件 | 展示范围 | 处理方式 |
|------|------|----------|----------|----------|
| 已验证 | `verified` | n>=100 且 CI 不含零 且 跨期一致>=60% | 每日提醒 + 总报 | 自动匹配信号，附加加成 |
| 候选观察 | `candidate` | 30<=n<100 且 mean_excess>0 | 仅研究报告 | 标注"待积累"，不进入提醒 |
| 待观察 | `pending` | n<30 或 mean_excess<=0 | 不展示 | 继续积累样本 |

### 1.2 准入判定函数

```python
def evaluate_pattern_eligibility(
    pattern: dict,
    cross_period_results: list[dict] | None = None,
) -> dict:
    """
    判定模式的准入等级。

    参数：
        pattern: 模式统计结果（含 n, mean_excess, ci_lo, ci_hi 等）
        cross_period_results: 跨时间段稳定性验证结果（可选）

    返回：
        {
            "status": "verified" / "candidate" / "pending",
            "eligible_for_reminder": bool,
            "eligible_for_brief": bool,
            "reason": str,
        }
    """
    n = pattern.get("n", 0)
    mean_excess = pattern.get("mean_excess") or 0
    ci_lo = pattern.get("mean_excess_ci_lo")
    ci_hi = pattern.get("mean_excess_ci_hi")

    # 候选观察：样本中等 + 正超额
    if 30 <= n < 100 and mean_excess > 0:
        return {
            "status": "candidate",
            "eligible_for_reminder": False,
            "eligible_for_brief": False,  # 仅研究报告
            "reason": f"样本{n}条，正超额{mean_excess:.2%}，待积累至100",
        }

    # 已验证：样本充足 + CI 不含零 + 跨期一致
    if n >= 100 and ci_lo is not None and ci_lo > 0:
        # 检查跨期一致性
        if cross_period_results:
            positive = sum(1 for r in cross_period_results
                           if (r.get("mean_excess") or 0) > 0)
            consistency = positive / len(cross_period_results)
            if consistency >= 0.6:
                return {
                    "status": "verified",
                    "eligible_for_reminder": True,
                    "eligible_for_brief": True,
                    "reason": f"n={n}, CI=[{ci_lo:.2%},{ci_hi:.2%}], 跨期一致{consistency:.0%}",
                }
            else:
                return {
                    "status": "candidate",
                    "eligible_for_reminder": False,
                    "eligible_for_brief": False,
                    "reason": f"CI不含零但跨期一致仅{consistency:.0%}(<60%)",
                }
        # 无跨期验证数据时，CI不含零即为候选
        return {
            "status": "candidate",
            "eligible_for_reminder": False,
            "eligible_for_brief": True,
            "reason": f"n={n}, CI不含零，待跨期验证",
        }

    # 待观察
    return {
        "status": "pending",
        "eligible_for_reminder": False,
        "eligible_for_brief": False,
        "reason": f"n={n}, 超额={mean_excess:.2%}",
    }
```

### 1.3 模式注册表

```json
// config/opportunity_pattern_registry.json
{
  "schema_version": "opportunity_pattern_registry_v1",
  "updated_at": "2026-05-24T07:00:00+00:00",
  "patterns": {
    "D4_14_Wexp_t": {
      "status": "verified",
      "d1_transition": "收缩有趋势 → 强势突破",
      "w1_context": "扩张有趋势",
      "n": 156,
      "mean_excess_20d": 0.0523,
      "ci_95": [0.028, 0.077],
      "win_rate": 0.583,
      "cross_period_consistency": 0.71,
      "first_verified_date": "2026-04-15",
      "last_updated": "2026-05-24",
      "eligible_for_reminder": true,
      "description": "D1从收缩有趋势跃迁至强势突破，W1扩张有趋势背景"
    },
    "D0_14_Wexp_t": {
      "status": "candidate",
      "n": 89,
      "mean_excess_20d": 0.0481,
      "eligible_for_reminder": false,
      "description": "D1从沉寂跃迁至强势突破，W1扩张有趋势"
    }
  }
}
```

---

## 2. 模式与现有策略的关系

### 2.1 三种交互模式

| 交互类型 | 条件 | 效果 |
|----------|------|------|
| **模式增强策略** | 策略信号的当日 D1 跃迁命中已验证模式 | 信号获得 pattern_boost 加成 |
| **模式独立触发** | 当日出现已验证模式但无策略信号 | 仅在总报中展示，不生成提醒 |
| **策略独立运行** | 策略信号触发但无匹配模式 | 正常运行，不受模式影响 |

### 2.2 模式增强策略的匹配逻辑

```python
def match_signal_to_pattern(
    signal_row: dict,
    current_transition: dict,
    verified_patterns: dict,
) -> dict | None:
    """
    检查信号是否命中已验证模式。

    参数：
        signal_row: 策略信号行（来自 strategy_signal_daily）
        current_transition: 当日 D1 跃迁（d1_from, d1_to, w1_state）
        verified_patterns: 已验证模式注册表

    返回：
        匹配的模式信息，或 None
    """
    pattern_code = encode_pattern_simple(
        current_transition["d1_from"],
        current_transition["d1_to"],
        current_transition["w1_state"],
    )

    pattern = verified_patterns.get(pattern_code)
    if not pattern or pattern.get("status") != "verified":
        return None

    return {
        "pattern_code": pattern_code,
        "pattern_description": pattern.get("description", ""),
        "pattern_mean_excess": pattern.get("mean_excess_20d", 0),
        "pattern_ci": pattern.get("ci_95", []),
        "pattern_win_rate": pattern.get("win_rate", 0),
        "pattern_n": pattern.get("n", 0),
        "pattern_boost": compute_pattern_boost(pattern),
    }
```

### 2.3 模式加成系数

```python
def compute_pattern_boost(pattern: dict) -> float:
    """
    模式对信号的加成系数。

    范围：1.00 - 1.15
    设计原则：加成幅度保守，不超过 15%
    """
    ci = pattern.get("ci_95", [])
    n = pattern.get("n", 0)
    win_rate = pattern.get("win_rate", 0)

    # 基础加成：CI 越窄、样本越大、胜率越高，加成越大
    ci_width = (ci[1] - ci[0]) if len(ci) == 2 else 0.10
    ci_tightness = max(0, 1.0 - ci_width / 0.10)  # CI 宽度越小越好

    n_factor = min(1.0, n / 500)  # 500 样本满分
    wr_factor = max(0, (win_rate - 0.5) * 2)  # 胜率 50% 为基线

    raw_boost = 0.05 + ci_tightness * 0.05 + n_factor * 0.03 + wr_factor * 0.02

    return round(min(0.15, max(0.0, raw_boost)), 3)
```

典型加成系数：

| 场景 | boost |
|------|-------|
| n=500, CI=[2%,8%], WR=58% | 0.120 |
| n=200, CI=[1%,9%], WR=55% | 0.090 |
| n=100, CI=[0%,10%], WR=52% | 0.060 |
| n=150, CI=[-1%,7%], WR=49% | 0.050 |

### 2.4 与适配度评分的衔接

```python
def apply_pattern_boost(
    base_fit_score: float,
    pattern_match: dict | None,
) -> float:
    """模式加成对适配度的调节。"""
    if pattern_match is None:
        return base_fit_score

    boost = pattern_match["pattern_boost"]
    return round(min(100, base_fit_score * (1.0 + boost)), 2)
```

### 2.5 完整调节链

```text
最终适配度 = base_fit_score
           × macro_factor          (0.80-1.20, 宏观)
           × chain_factor          (0.80-1.20, 产业链)
           × state_factor          (0.85-1.15, State环境)
           × phase_factor          (0.80-1.15, 市场阶段)
           × env_category_factor   (0.88-1.12, W1×MN1大周期)
           × pattern_boost         (1.00-1.15, 模式加成) ← 新增
```

pattern_boost 是乘法因子中幅度最小的（上限 1.15），因为模式是附加证据而非核心驱动。

---

## 3. 展示设计

### 3.1 总报：新增"今日机会模式"模块

在 `daily_research_brief.py` 的 chief 模式中新增一个章节。

#### 模块位置

```text
一、宏观环境速览
二、产业链景气扫描
三、行业-策略适配
四、今日机会模式        ← 新增
五、重点个股信号
六、综合适配建议
```

#### 展示内容

```markdown
## 四、今日机会模式

当日触发已验证模式 3 个，匹配标的 12 只。

### D4→14 W_exp_t：收缩释放突破（n=156, 超额+5.2%）
| 标的 | 行业 | 当日 D1 变化 | 匹配策略 | 策略适配度 |
|------|------|-------------|----------|-----------|
| 002049.SZ 紫光国微 | 电子 | 4→14 | VCP entry | 最佳适配+12% |
| 300969.SZ 恒帅股份 | 汽车 | 4→14 | VCP entry | 最佳适配+10% |
| ... |

### D0→14 W_exp_t：沉寂跃迁突破（n=89, 待积累至100）
以下模式为候选观察，仅展示方向，不进入提醒：
- 300731.SZ 科创新源（化工）

### 今日无匹配模式的已验证模式
以下已验证模式今日未触发：
- D8→14 W_exp_t（刚扩张→强势突破）— 今日无标的满足
```

#### 展示规则

| 场景 | 展示行为 |
|------|----------|
| 有已验证模式命中 | 展示模式详情 + 匹配标的列表 |
| 仅候选模式命中 | 标注"候选观察，待积累"，不展示具体标的 |
| 无模式命中 | 展示"今日无已验证模式触发" |
| 模式命中但无策略信号 | 展示模式但标注"仅模式触发，无策略信号" |

### 3.2 提醒卡片：跃迁模式加成标签

当信号命中已验证模式时，在提醒卡片中新增一行。

#### 卡片展示

```text
┌──────────────────────────────────────────────────────────┐
│ 002049 紫光国微                                           │
│ ──────────────────────────────────────────────────────── │
│ 策略信号：VCP突破确认          适配度：最佳适配(+12%)     │
│ 生命周期：趋势新生                                        │
│ State 环境：MN1: E  W1: E  D1: E  (ef=3)                 │
│ D1 标签：波动稳定 / D1收缩充分 / 三周期共振新近形成        │
│ 大周期背景：大周期共振 — 月线+周线均扩张有趋势             │
│ 跃迁模式：D4→14 收缩释放突破 | 历史+5.2% | n=156  ← 新增 │
│ 基本面：质量健康 / 现金流健康                              │
│ 统计：收缩后释放路径，20d超额 +1.67%                      │
└──────────────────────────────────────────────────────────┘
```

#### 展示条件

```python
def should_show_pattern_tag(signal_row: dict) -> bool:
    """是否在提醒卡片中展示跃迁模式标签。"""
    pattern = signal_row.get("matched_pattern_info")
    if not pattern:
        return False
    # 仅已验证模式展示
    return pattern.get("pattern_status") == "verified"
```

#### 标签内容

```python
def render_pattern_tag(signal_row: dict) -> str:
    """渲染跃迁模式标签行。"""
    pattern = signal_row.get("matched_pattern_info", {})
    code = pattern.get("pattern_code", "")
    desc = pattern.get("pattern_description", "")
    excess = pattern.get("pattern_mean_excess", 0)
    n = pattern.get("pattern_n", 0)
    boost = pattern.get("pattern_boost", 0)

    return (
        f"  跃迁模式：{desc} | "
        f"历史{excess:+.1%} | n={n} | 加成{boost:+.1%}"
    )
```

---

## 4. 与三重共振的衔接

### 4.1 当前三重共振

```text
维度 1: 宏观 → macro_factor
维度 2: 产业链 → chain_factor
维度 3: State → state_factor × phase_factor × env_category_factor
```

### 4.2 模式作为 State 维度的补充证据

模式不作为独立的第四维度，而是 **State 维度的附加证据层**：

```text
维度 3: State → state_factor × phase_factor × env_category_factor × pattern_boost
```

理由：
- 模式本身从 State 数据中挖掘，属于 State 维度的信息延伸
- 避免维度膨胀（四维共振已足够复杂）
- pattern_boost 幅度小（0-15%），适合作为附加乘数而非独立维度

### 4.3 四维同时利好的识别

虽然模式不作为独立维度，但系统可以识别"四维同时利好"的最高置信度场景：

```python
def identify_highest_conviction(
    signal_row: dict,
    macro_dir: str,
    chain_dir: str,
    state_dir: str,
    pattern_match: dict | None,
) -> dict:
    """
    识别最高置信度场景：宏观×产业链×State×模式四维同时利好。
    """
    all_positive = (
        macro_dir == "positive"
        and chain_dir == "positive"
        and state_dir == "positive"
        and pattern_match is not None
    )

    if all_positive:
        return {
            "conviction_level": "highest",
            "conviction_label": "四维共振",
            "dimensions": {
                "macro": "positive",
                "chain": "positive",
                "state": "positive",
                "pattern": pattern_match["pattern_code"],
            },
            "description": "宏观+产业链+State+跃迁模式四维同时利好",
        }

    return {"conviction_level": "normal", "conviction_label": ""}
```

### 4.4 四维共振的展示

当信号达到"四维共振"时，在提醒卡片中展示特殊标记：

```text
适配度：最佳适配(+12%)  ★ 四维共振
```

---

## 5. 新增字段清单

### 5.1 strategy_signal_daily 表

```sql
ALTER TABLE strategy_signal_daily ADD COLUMN matched_pattern VARCHAR DEFAULT '';
ALTER TABLE strategy_signal_daily ADD COLUMN pattern_boost DOUBLE DEFAULT 0.0;
ALTER TABLE strategy_signal_daily ADD COLUMN conviction_level VARCHAR DEFAULT 'normal';
```

### 5.2 strategy_fit_observer 表

```sql
ALTER TABLE strategy_fit_log ADD COLUMN matched_pattern VARCHAR DEFAULT '';
ALTER TABLE strategy_fit_log ADD COLUMN pattern_boost DOUBLE DEFAULT 0.0;
```

---

## 6. 模式生命周期管理

### 6.1 新模式发现

```text
模式挖掘脚本产出候选模式
  → 准入判定（candidate/pending）
  → 写入 opportunity_pattern_registry.json
  → 不进入提醒
```

### 6.2 模式升级

```text
候选模式积累到 n>=100
  → 跨期稳定性验证
  → CI 不含零 + 跨期一致>=60%
  → 状态升级为 verified
  → 写入注册表
  → 开始进入提醒和总报
```

### 6.3 模式降级

```text
已验证模式的新增样本导致 CI 包含零
  → 状态降级为 candidate
  → 从提醒中移除
  → 继续观察
```

### 6.4 模式过期

```text
已验证模式超过 6 个月无新样本触发
  → 标记为 stale
  → 从提醒中移除
  → 保留注册表记录供历史参考
```

---

## 7. 与现有模块的改动清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `scripts/mine_opportunity_patterns.py` | 新增 | 模式挖掘脚本（Kimi 实现中） |
| `scripts/strategy_signal_ledger.py` | 修改 | 信号行新增 matched_pattern / pattern_boost / conviction_level |
| `scripts/strategy_reminder_brief.py` | 修改 | 提醒卡片新增跃迁模式标签行 |
| `scripts/daily_research_brief.py` | 修改 | 总报新增"今日机会模式"模块 |
| `scripts/strategy_fit_observer.py` | 修改 | 适配度观察新增 pattern_boost 记录 |
| `config/opportunity_pattern_registry.json` | 新增 | 已验证模式注册表 |
| `docs/DATA_DRIVEN_PATTERN_MINING_FRAMEWORK.md` | 已完成 | 模式挖掘框架 |
| `docs/OPPORTUNITY_PATTERN_TO_SIGNAL_SPEC.md` | 本文 | 转化规范 |
