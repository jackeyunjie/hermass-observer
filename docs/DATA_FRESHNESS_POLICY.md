# Data Freshness Policy

日期：2026-05-29

目标：避免把低频或过旧数据冒充成“今天的主判断”，同时也避免误伤本来就按周/低频更新的数据。

---

## 1. 原则

Hermass 前台不再用单一“必须同日”的规则判断所有数据。

改为两维判断：

1. 更新节奏
   - 日更
   - 周更 / 准日更
   - 低频

2. 使用角色
   - 主判断
   - 辅助判断
   - 背景参考

只有同时满足“节奏允许范围”和“使用角色要求”的数据，才允许参与前台判断。

---

## 2. 分层规则

### 2.1 核心交易底座

这类数据属于 **主判断**，要求最严格。

| 模块 | 典型路径 | 节奏 | 允许滞后 |
|------|----------|------|----------|
| Foundation DB | `outputs/p116_foundation_YYYYMMDD/` | 日更 | 0 天 |
| state_cache | `outputs/state_cache/` | 日更 | 0 天 |
| strategy_signals | `outputs/strategy_signals/` | 日更 | 0 天 |
| forward_observation | `outputs/forward_observation/` | 日更 | 0 天 |
| daily_snapshot | `outputs/daily_snapshot/` | 日更 | 0 天 |

处理规则：

- 不满足时，不应继续宣称“今天可用”
- 对应页面应直接降级或阻断

### 2.2 执行与共振辅助层

这类数据属于 **辅助判断**，允许存在一定滞后，但不能伪装成当日主判断。

| 模块 | 典型路径 | 节奏 | 允许滞后 |
|------|----------|------|----------|
| unified_view | `outputs/unified_view/` | 周更 / 准日更 | 7 天 |
| industry_rotation | `outputs/industry_rotation/` | 周更 / 低频 | 7 天 |
| reward_risk | `outputs/reward_risk/` | 周更 / 低频 | 7 天 |

处理规则：

- 在允许范围内：可展示，但必须标注来源日期
- 超过允许范围：退出前台主判断，页面只保留结构主线

### 2.3 背景参考层

这类数据属于 **背景参考**，可以低频，但绝不能被表述成“今日强信号”。

| 模块 | 典型路径 | 节奏 | 允许滞后 |
|------|----------|------|----------|
| macro_chain_prior | `outputs/macro_chain_prior/` | 低频 | 10 天 |
| macro_snapshot | `outputs/macro/` | 低频 | 10 天 |
| industry_chain / chain_dynamics | `outputs/industry_chain/` | 低频 | 10 天 |
| industry_position | `outputs/industry_chain/industry_position_*` | 低频 | 10 天 |

处理规则：

- 允许作为背景说明
- 不允许单独裁决今天该不该做、哪个方向一定更强

---

## 3. 页面行为

### 3.1 首页

- 显示外围数据新鲜度提示
- 明确“低频背景不会冒充成今日主判断”

### 3.2 市场页

- `market_phase` 和 `market_assets_state` 属于主判断
- `macro_chain_prior` 属于背景参考
- 若背景参考过旧：保留结构判断，弱化宏观话术

### 3.3 执行页

- `State / D1 支撑 / signal / forward_observation` 作为核心
- `资金流 / 板块承接 / reward_risk` 作为辅助
- 辅助层过旧时：
  - 继续展示结构主线
  - 停止把资金流和板块承接写成强确认

### 3.4 研究页

- `Foundation + State` 为核心
- `moneyflow / industry_rotation` 为辅助背景
- 辅助背景过旧时：
  - 提示来源日期
  - 不把其写成今天的强证据

---

## 4. 不允许的误导

以下行为禁止：

1. 文件名是 `20260529`，但 payload 内日期仍是旧日期
2. latest 文件已更新，但真实内容未更新
3. 用 5/22 的资金流去写“今天主力确认”
4. 用周更行业承接去写“今日行业强确认”
5. 把背景参考层的话术写成当日强执行依据

---

## 5. 当前代码口径

网站当前已采用：

- `市场阶段`：日更 + 主判断
- `宽基与行业 ETF`：日更 + 主判断
- `个股资金流与统一视图`：周更 / 准日更 + 辅助判断
- `行业承接`：周更 / 低频 + 辅助判断
- `宏观先验`：低频 + 背景参考

这意味着：

- 不是所有数据都要求与 `daily_snapshot` 同日
- 但所有低频数据都必须显式标注，不再静默混入今日判断

---

## 6. 部署要求

部署前至少满足：

1. 核心交易底座同日对齐
2. 辅助层和背景层显式标注日期
3. 超过阈值的外围层不再参与前台主判断

只满足第 2 条而不满足第 1 条，不可宣称“今日全站已对齐”。
