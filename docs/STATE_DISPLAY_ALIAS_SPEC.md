# State Display Alias Spec

版本：v1.0  
日期：2026-05-28  
范围：A 股 External Research Response / 展示层

---

## 1. 目标

本规范只定义 **State 的前台展示别名和结构解读**，不修改任何底座编码。

一句话边界：

- `state_score / state_hex / ef_count` 继续以 [STATE_BASE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/STATE_BASE_CONTRACT.md) 为准
- `E/F/C/...` 不改、不重算、不替换
- 用户侧研究卡可以在保留 raw state 的同时，追加更自然的结构语义
- 当持续性数据可用时，优先输出动态节奏先验，而不是只使用固定话术

---

## 2. 分层原则

```text
Layer 2 / State 底座
  state_score / state_hex / ef_count
       ↓
Layer 3 / Display Alias
  alias_label / structure_explanation
       ↓
Layer 4 / 卡片展示
  quick / deep / evidence
```

原则：

1. raw state 永远保留
2. alias 只是解释，不是替代
3. 结构解读必须是规则产出，不允许模型自由发挥

---

## 3. 维度翻译规则

State 的四个维度继续使用底座定义：

- `base`
- `trend_bit`
- `position_bit`
- `volatility_bit`

前台翻译如下：

| 维度 | 原始含义 | 展示语义 |
|------|----------|----------|
| `base=8` | 扩张 | `扩张` |
| `base=0` | 收缩 | `收缩` |
| `trend_bit=1` | 有趋势 | `趋势` |
| `trend_bit=0` | 无趋势 | `无方向` |
| `position_bit=2` | 突破 | `突破` |
| `position_bit=0` | 区间内/未突破 | `未突破` |
| `volatility_bit=1` | 波动扩张 | `活跃` |
| `volatility_bit=0` | 波动稳定 | `稳定` |

负值 state 不改写定义，只在末尾追加：

- `（负向）`

---

## 4. 别名字典

### 4.1 基本格式

前台别名格式固定为：

```text
{base_alias}·{trend_alias}·{position_alias}·{vol_alias}
```

示例：

| Raw State | Score | Display Alias |
|-----------|-------|---------------|
| `E` | 14 | `扩张·趋势·突破·稳定` |
| `F` | 15 | `扩张·趋势·突破·活跃` |
| `C` | 12 | `扩张·趋势·未突破·稳定` |
| `0` | 0 | `收缩·无方向·未突破·稳定` |
| `-C` | -12 | `收缩·趋势·未突破·稳定（负向）` |

### 4.2 不做的事

以下都不做：

- 不把 `E/F` 改成“牛/熊”
- 不把 raw state 直接翻成“买点/卖点”
- 不给 alias 添加主观倾向词，如“极强”“必涨”“危险”

---

## 5. 结构解读模板

### 5.1 展示形式

卡片中建议采用两行：

```text
State：E/E/F
结构解读：月线周线全面强势，日线波动偏活跃
```

### 5.2 解读规则

解读模板只消费：

- `mn1_state_hex`
- `w1_state_hex`
- `d1_state_hex`
- `ef_count`
- `market_phase`

建议规则：

| 条件 | 结构解读模板 |
|------|--------------|
| `ef_count = 3` 且 D1=`F` | `中大周期偏强，日线处于高活跃推进段` |
| `ef_count = 3` 且 D1=`E` | `中大周期偏强，日线推进结构相对稳定` |
| `ef_count = 2` | `中大周期已有共振，短周期仍在确认` |
| `ef_count = 1` | `只有单周期保持强势，整体共振不足` |
| `ef_count = 0` | `当前未形成 E/F 共振，各周期未达最强状态` |

### 5.3 周期粒度解释

更细粒度可叠加：

- `MN1`：大级别背景
- `W1`：中期趋势支撑
- `D1`：短期推进/活跃度

例如：

```text
State：E/E/F
结构解读：月线与周线保持扩张趋势，日线已突破且波动活跃。
```

当三周期存在强弱错位时，优先使用“背景 vs 确认”措辞：

| 条件 | 推荐解读 |
|------|----------|
| `MN1=E/F` 且 `D1` 非 `E/F` | `大级别背景偏强，短期仍在确认` |
| `MN1` 非 `E/F` 且 `D1=E/F` | `短期已有推进，但大级别背景仍未完全配合` |
| `W1=E/F` 且 `D1` 较弱 | `中期趋势仍在，短期节奏转入确认` |

---

## 6. 卡片展示规则

### 6.1 Quick Card

建议：

- 保留 `State：E/E/F`
- 追加一句简短动态先验或结构解读
- 不展开四维别名全文

示例：

```text
State：E/E/F（三周期共振刚形成，先验上更偏向观察共振能否延续，而不是直接外推强度。）
```

当持续性数据不可用时，退回结构解读：

```text
State：E/E/F（中大周期偏强，日线处于高活跃推进段）
```

### 6.2 Deep Card

建议：

- 保留 raw state
- 展示结构解读
- 在 evidence 或 appendix 需要时才展开单周期 alias
- 展示持续性与节奏先验

示例：

```text
State 核心：MN1=E / W1=E / D1=F
结构解读：月线周线全面强势，日线处于波动更高的推进段
节奏先验：大周期保持扩张趋势，D1 处于突破后的活跃推进段，先验上更容易先出现短周期节奏切换。
```

### 6.3 Evidence Card

建议：

- raw state 为主
- 可额外显示 alias，用于解释编码
- 适合放审计式说明，不适合写判断性语言

---

## 7. 与现有模块的关系

### 7.1 保持不变

- [STATE_BASE_CONTRACT.md](/Users/lv111101/Documents/hermass-observer-product/docs/STATE_BASE_CONTRACT.md)
- `d1_perspective_state`
- `mn1_state_hex / w1_state_hex / d1_state_hex`
- `ef_count`

### 7.2 可在展示层追加

- `state_alias_map`
- `structure_explanation`
- `state_display_label`

这些字段都属于 formatter 或 display helper，不应写回 Foundation DB。

---

## 8. 实施顺序

推荐顺序：

1. 先实现 display helper：`state_hex -> alias`
2. 再实现 `state_combo -> structure_explanation`
3. 先接 deep/evidence card
4. 最后再接 quick card 和飞书入口

---

## 9. 与 Claude 讨论的边界

如果需要让 Claude 评审，建议只讨论两个窄问题：

1. alias 字典是否够自然、是否有歧义
2. `ef_count + state_combo + market_phase` 的结构解读模板是否够稳定

不需要和 Claude 讨论：

- State 编码本身
- E/F 定义
- ef_count 计算
- 底座公式
