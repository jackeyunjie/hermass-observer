# Hermass Observer 首席架构顾问报告

> 角色：Codex 5.5x 风格——极强工程直觉，偏好机械约束，对可量化事物极度敏感，对哲学映射持务实态度（能落地就用）。

---

## Q1 产品内核：EF 共振筛选 vs 多周期 Agent 市场态运转系统

### 判断

内核必须是**"多周期 Agent 市场态运转系统"**，而非"EF 共振筛选"。EF 共振只是一个衍生的筛选视图（view），不是系统本身。

### 推理链

把系统比作气象台。气象台的核心不是"暴雨预警"，而是"大气态运转观测"——暴雨预警只是从完整大气态中派生出的一个警报条件。同理，EF 共振是从 State 编码矩阵中派生出的一个筛选条件。如果产品定位为"EF 筛选器"，等于把整个大气态系统降格为一个暴雨预警器，丢掉了：

1. **收缩态（hex 0-3）** 的信息——当前 EF 筛选只看 14/15，但收缩态（0-3）才是 VCP 策略的入场前兆，这部分股票在 EF 筛选中完全不可见。
2. **状态迁移（transition）** 的信息——一只股票从 hex 3 → hex 8（从收缩进入扩张），这个跳变本身就是强信号，但 EF 筛选只能看到"它还不算 E/F"。
3. **策略匹配的多样性**——VCP 在 emergence 阶段入场（不是所有周期都 E/F），2560 在 progression 阶段入场，布林强盗在 extension 阶段入场。三种策略需要的 State 组合不同，EF 筛选只覆盖了其中一种。

首页应该展示：
- **市场相（Market Phase）指示器**：当前处于 contraction / emergence / progression / extension / risk release 五相中的哪一个。这是系统级的顶层摘要，从全市场 State 分布统计得出。
- **三周期热力矩阵**：MN1 × W1 × D1 的 State 分布热力图，让用户一眼看到"哪个周期在主导"。
- **行业共振排名**：SW 一级行业的 EF2 率排名 + 行业 prosperity 分数。
- **前向观察账本摘要**：累计样本数、各策略命中率、距下一次校准触发器的进度。

应该从首页去掉或降级的：
- 把"EF 股票列表"从首页主位降级为一个可点击的二级视图。
- 去掉"Top 100 × 3天"这种静态展示，改为动态的"今日变化"视图（新进入 EF 的、退出 EF 的、状态跳变的）。

### 风险与盲点

风险是"运转系统"这个定位太抽象，普通用户难以理解。需要一个类比锚点（气象台、体检报告）。另外，前端复杂度会显著增加——热力图和相态指示器的可视化设计需要投入。

### 与其他答案的关系

与 Q4（Agent 自组织）共识：只有定位为运转系统，Agent 才有"运转"的空间。如果定位为筛选器，Agent 就只是查询接口。与 Q7（收缩观测）共识：收缩态的信息只有在"运转系统"框架下才被完整保留和监控。

---

## Q2 三周期真实权重：D1/W1/MN1 权重分配

### 判断

推荐方案：**D1=50%, W1=30%, MN1=20%**，但不是固定权重——而是分场景动态调整。

### 推理链

先看数据事实：

| 指标 | D1 | W1 | MN1 |
|------|----|----|-----|
| 与次日回报 Pearson r | 0.205 | 0.082 | 0.061 |
| 独立 EF 率 | ~35% | 13.0%（最严格瓶颈） | ~25% |
| 方向波动 | ±24pp | ±15pp | ±10pp（最稳定） |

纯看短期预测力，D1 是 W1 的 2.5 倍、MN1 的 3.4 倍。但权重不能只按 r 值比例分配，原因有三：

**第一，r 衡量的是线性相关性，不是策略贡献。** W1 的 r=0.082 看似低，但它是 EF2 的瓶颈——只有 13% 的股票能通过 W1 的 EF 门槛。这意味着 W1 在过滤噪声方面贡献最大。一个过滤器的重要性不能只用它与输出的相关性来衡量，还要看它拒绝了多少假阳性。

**第二，MN1 的低相关性是特性而非缺陷。** MN1 方向波动只有 ±10pp，这意味着它很少翻转。当 MN1 确实翻转时（从非 EF 进入 EF，或反过来），这是一个极其可靠的宏观 regime 信号。低频信号的特点是：日常贡献小，关键节点贡献巨大。

**第三，不同策略需要的权重不同。** VCP 策略在收缩突破时刻入场，这时候 D1 的高频信号最重要（捕捉突破瞬间）；2560 趋势跟踪需要 W1 确认中期趋势方向；布林强盗在 extension 阶段需要 MN1 确认大趋势不会反转。

分场景调整方案：

```python
def get_period_weights(market_phase: str, strategy: str) -> dict:
    # 基础权重
    base = {"D1": 0.50, "W1": 0.30, "MN1": 0.20}
    
    # 场景修正器（乘法后归一化）
    phase_modifier = {
        "contraction":  {"D1": 0.8, "W1": 1.0, "MN1": 1.5},  # 收缩期MN1更关键
        "emergence":    {"D1": 1.3, "W1": 1.2, "MN1": 0.8},  # 突破期D1最关键
        "progression":  {"D1": 1.0, "W1": 1.3, "MN1": 1.0},  # 趋势期W1最关键
        "extension":    {"D1": 0.9, "W1": 1.0, "MN1": 1.3},  # 延展期MN1防反转
        "risk_release": {"D1": 0.7, "W1": 0.8, "MN1": 1.8},  # 风险释放MN1主导
    }
    
    strategy_modifier = {
        "vcp":              {"D1": 1.4, "W1": 0.9, "MN1": 0.7},
        "ma2560":           {"D1": 0.9, "W1": 1.3, "MN1": 0.8},
        "bollinger_bandit": {"D1": 1.0, "W1": 1.0, "MN1": 1.2},
    }
    
    pm = phase_modifier.get(market_phase, {"D1": 1, "W1": 1, "MN1": 1})
    sm = strategy_modifier.get(strategy, {"D1": 1, "W1": 1, "MN1": 1})
    
    raw = {k: base[k] * pm[k] * sm[k] for k in base}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}
```

**MN1 不可或缺的根本原因：** MN1 是系统的"锚"。当 D1 和 W1 同时发出假信号（这在日线级别很常见），MN1 的稳定态是唯一能阻止系统在大趋势向下时仍然满仓追涨的约束。去掉 MN1 等于去掉宏观 filter，回测可能好看，实盘会在第一次大级别调整中损失惨重。行业 EF2 率 0%-90% 的差异进一步证明：某些行业的 MN1 长期锁定在非 EF 态，这是一种极其有价值的"否决票"。

### 风险与盲点

权重方案的验证需要至少 252 个交易日的 walk-forward OOS 测试。当前前向观察账本只有 191 个样本，不够分策略验证。盲点是：我没有考虑三周期之间的交互项（interaction），可能存在"当三周期全部 E/F 时信号质量指数级提升"的非线性效应。

### 与其他答案的关系

与 Q3（行业权重）存在耦合：行业 EF2 率差异巨大，说明 MN1 在某些行业可能永远是非 EF，此时 MN1 对该行业的权重应该被"行业否决"替代。与 Q6（强化学习因子）共识：权重最终应该由 walk-forward 数据驱动而非人工设定。

---

## Q3 行业该占多大权重

### 判断

行业应该作为**独立的门控维度（gate dimension）**，而不是一个加权维度。具体来说：行业是"通过/不通过"的门，不是"加几分"的因子。

### 推理链

数据事实：SW 一级行业 EF2 率从 0%（国防军工）到 90%（建筑材料），电子行业占 EF 信号 37.4%，半导体 EF2=85.2% vs 电池=33.3%。

这种极端差异说明行业不是"给个股信号加一点分"的问题，而是"这个行业本身有没有行情"的问题。用加权模型处理会导致两个问题：

1. **低 EF2 行业的噪声个股被行业高分拉高**。比如某军工股 D1=W1=E，但整个军工行业 EF2=0%，这意味着该股可能只是个股事件驱动（重组/消息），不是行业趋势，不应按趋势策略入场。
2. **高 EF2 行业的弱个股被行业高分保护**。比如某建筑材料股 EF2=90% 但自身只有 1 个周期 E/F，行业热度不能替代个股状态。

门控方案：

```python
class IndustryGate:
    """行业门控：三层过滤"""
    
    # 第一层：行业EF2率门槛（SW一级）
    L1_MIN_EF2_RATE = 0.15  # 低于15%的行业，其个股必须3周期全EF才入选
    
    # 第二层：行业prosperity分数（0-10，来自chain_prosperity_scoring_model）
    L2_MIN_PROSPERITY = 4.0  # 低于4分的行业，仓位上限砍半
    
    # 第三层：二级行业交叉验证
    L2_INDUSTRY_OVERRIDE = True  # 如果二级行业EF2率与一级行业方向相反，以二级为准
    
    def evaluate(self, stock_code: str) -> IndustryGateResult:
        l1_industry = get_sw_l1(stock_code)
        l2_industry = get_sw_l2(stock_code)
        
        l1_ef2_rate = get_industry_ef2_rate(l1_industry)
        l2_ef2_rate = get_industry_ef2_rate(l2_industry)
        
        # 门控逻辑
        if l1_ef2_rate < self.L1_MIN_EF2_RATE:
            return IndustryGateResult(
                passed=False,
                reason=f"行业{l1_industry} EF2率{l1_ef2_rate:.1%}低于门槛",
                override_condition="三周期全EF可覆盖"
            )
        
        prosperity = get_industry_prosperity(l1_industry)
        position_cap = 1.0 if prosperity >= self.L2_MIN_PROSPERITY else 0.5
        
        # 二级行业方向验证
        if self.L2_INDUSTRY_OVERRIDE:
            if l2_ef2_rate > l1_ef2_rate * 1.5:
                # 二级行业显著强于一级，用二级数据
                prosperity = max(prosperity, get_industry_prosperity(l2_industry))
        
        return IndustryGateResult(
            passed=True,
            position_cap=position_cap,
            prosperity_score=prosperity
        )
```

**二级行业必须独立使用。** 电子行业一级 EF2=37.4%，但半导体（二级）EF2=85.2%，消费电子（二级）可能只有 15%。如果只用一级行业，要么把半导体的强信号稀释掉，要么把消费电子的弱信号拉高。当前 `industry_etf_proxy_whitelist.json` 已经在做一级行业到 ETF 的映射，需要新增二级行业到 ETF 的映射。

### 风险与盲点

SW 行业分类本身有滞后性——公司主业变更后分类不立即更新。另外，行业门控可能在行业轮动剧烈时错过"先知先觉"的个股（行业 EF2 率还没上来但龙头已经启动）。缓解方案：行业门控只约束仓位上限，不完全否决个股信号。

### 与其他答案的关系

与 Q2（三周期权重）的矛盾：Q2 说 MN1 是"否决票"，这里说行业也是"否决票"。两个否决票叠加会导致信号通过率极低。解决方案是：两个否决票不同时生效——当 MN1 和行业都否定时执行否决，当只有一个否定时降低仓位但不完全否决。与 Q1（产品内核）共识：行业门控只有在"运转系统"框架下才有意义，因为它依赖行业 prosperity 分数和 chain dynamics 数据。

---

## Q4 从查询型 Agent 到自组织 Agent

### 判断

渐进升级路径分四个阶段，每阶段有明确的工程验证标准。核心原则是：**自组织不等于自主决策，而是"自主发现问题 + 人类确认决策"**。

### 推理链

当前系统的 7 个 Agent（market_analyst / strategy_advisor / risk_guardian / cognitive_detective / coach / monetization_butler / contraction_observer）都是查询型：用户调用 → Agent 从 foundation DB 读数据 → 返回结果。这是正确的起步，但要升级为自组织，需要增加三个能力层：

**阶段 1：事件驱动监控（Event-Driven Monitoring）**

让 Agent 从"被调用"变成"被触发"。不是 Agent 自己决定做什么，而是系统事件触发 Agent 运行。

```python
# 事件总线（轻量实现：Redis Stream 或 DuckDB 的 temporal trigger）
class EventBus:
    events = {
        "state_transition": [],      # State跳变事件
        "ef_threshold_crossed": [],   # EF门槛穿越事件
        "industry_phase_change": [],  # 行业相变事件
        "calibration_due": [],        # 校准到期事件
        "forward_observation_mature": [],  # 前向观察成熟事件
    }
    
    def subscribe(self, event_type: str, agent_handler: callable):
        self.events[event_type].append(agent_handler)
    
    def emit(self, event_type: str, payload: dict):
        for handler in self.events[event_type]:
            handler(payload)
```

验证标准：系统能在 State 跳变发生后 5 秒内触发相关 Agent，且不误触发（precision > 99%）。

**阶段 2：Agent 间协作协议（Collaboration Protocol）**

定义 Agent 之间的消息契约。关键是：每个 Agent 有明确的输入契约（accept）和输出契约（produce），像微服务一样对接。

```python
@dataclass
class AgentMessage:
    from_agent: str
    to_agent: str
    message_type: str  # "observation" | "alert" | "recommendation" | "challenge"
    payload: dict
    confidence: float  # 0-1
    requires_ack: bool = False
    ttl_seconds: int = 3600

# 协作示例
# contraction_observer 检测到全市场收缩率创新高
# → 发消息给 market_analyst："市场可能进入收缩相"
# → market_analyst 验证后发消息给 strategy_advisor："VCP策略准备就绪"
# → strategy_advisor 发消息给 risk_guardian："请评估当前入场风险"
# → risk_guardian 回复："仓位上限建议80%"
```

验证标准：至少 3 个 Agent 能在一个触发事件后完成链式协作，且消息不丢失、不重复。

**阶段 3：自主判断（Autonomous Judgment）**

Agent 可以自主做出"初步判断"，但必须经过人类确认才能执行。

```python
class AutonomousJudge:
    """Agent自主判断框架"""
    
    def evaluate_and_propose(self, context: AgentContext) -> AgentProposal:
        # 1. 模式匹配：当前状态是否匹配已知模式
        pattern_match = self.pattern_library.match(context)
        
        # 2. 历史回溯：类似情况下系统过去的表现
        historical = self.forward_ledger.query_similar(context, top_k=10)
        
        # 3. 置信度评估
        confidence = self.compute_confidence(pattern_match, historical)
        
        # 4. 如果置信度 > 阈值，生成提案
        if confidence >= self.PROPOSAL_THRESHOLD:  # 例如 0.7
            return AgentProposal(
                action="ALERT_USER",
                reasoning=self.explain_reasoning(context, pattern_match, historical),
                confidence=confidence,
                auto_executable=False  # 永远不自动执行，只提案
            )
        return None
```

验证标准：Agent 提案的准确率（经人类评审）在连续 30 天内 > 70%。

**阶段 4：自我进化（Self-Evolution）**

Agent 的参数和规则可以通过校准触发器自动调整。这已经部分实现（calibration_trigger.py 的三重门机制），需要扩展为：

```python
class SelfEvolution:
    def evolve(self, strategy: str, forward_data: pd.DataFrame):
        # 1. Walk-forward验证：当前参数 vs 候选参数
        current_score = self.walk_forward_test(strategy, self.current_params[strategy])
        candidate_params = self.parameter_search(strategy, forward_data)
        candidate_score = self.walk_forward_test(strategy, candidate_params)
        
        # 2. 统计显著性检验
        if self.is_significantly_better(candidate_score, current_score, alpha=0.05):
            # 3. 生成进化提案
            return EvolutionProposal(
                strategy=strategy,
                current_params=self.current_params[strategy],
                proposed_params=candidate_params,
                improvement_estimate=candidate_score - current_score,
                requires_human_approval=True
            )
```

验证标准：进化后的参数在 OOS 测试中持续优于进化前参数，且进化频率不超过每季度一次（防止过拟合）。

### 风险与盲点

最大风险是"自组织幻觉"——Agent 看似在自主运作，实际上只是在产生大量低价值告警。验证标准必须包含"信噪比"指标：Agent 自主发起的消息中，被人类确认为有价值的比例。如果低于 50%，说明自组织能力不成熟，应回退到上一阶段。

### 与其他答案的关系

与 Q1（产品内核）共识：自组织 Agent 只有在"运转系统"定位下才有意义。与 Q8（构建验证）强耦合：自组织 Agent 的测试比查询型 Agent 复杂一个数量级，因为行为不确定性增加了。与 Q9（量变到质变）共识：阶段 4 的自我进化就是"质变"的一种表现形式。

---

## Q5 孙子兵法与道德经

### Q5a 孙子"知胜有五"映射

**判断：** 这五个原则可以直接映射为多 Agent 体系的设计约束。

| 孙子原文 | 工程映射 | 实现方式 |
|----------|----------|----------|
| 知可以战与不可以战者胜 | Agent 知道何时该发出信号、何时不该 | 行业门控（Q3）+ 宏观三层过滤（已有 macro_environment_filter）|
| 识众寡之用者胜 | 根据信号强度调配仓位 | risk_guardian 的动态仓位管理 |
| 上下同欲者胜 | 所有 Agent 对当前市场相有一致理解 | market_analyst 作为"共识锚"——所有 Agent 在决策前先查询当前 market_phase |
| 以虞待不虞者胜 | 前向观察账本 + 校准触发器 | 已有的 forward_observation_ledger + calibration_trigger |
| 将能而君不御者胜 | Agent 有自主权但受约束 | 阶段 3 自主判断框架（Q4）——Agent 可以提案，但人类有否决权 |

**"将能而君不御"的工程实现：**

这是一个权限模型问题。核心是定义每个 Agent 的"自主权边界"：

```python
class AgentAuthority:
    # 完全自主（不需要人类确认）
    AUTO = {
        "market_analyst": ["compute_state", "detect_phase", "emit_event"],
        "contraction_observer": ["compute_contraction_metrics", "detect_squeeze"],
        "risk_guardian": ["compute_risk_grade", "set_position_cap"],
    }
    
    # 需要人类确认
    CONFIRM = {
        "strategy_advisor": ["propose_entry", "propose_exit"],
        "cognitive_detective": ["flag_bias", "challenge_assumption"],
    }
    
    # 人类必须主导
    HUMAN_ONLY = {
        "monetization_butler": ["execute_trade", "modify_portfolio"],
        "coach": ["modify_strategy_rules", "change_calibration_threshold"],
    }
```

原则：信息生产类操作（计算、检测、告警）完全自主；决策类操作（入场、出场、修改参数）需要人类确认；执行类操作（下单、修改策略规则）必须人类主导。

### Q5b 道德经第25章映射

**"大曰逝，逝曰远，远曰反"映射 MN1→W1→D1：**

| 道德经 | 周期映射 | 工程含义 |
|--------|----------|----------|
| 大曰逝（大的意味着运行不息） | MN1：月线是"大势"，它永远在运行，方向变化最慢但最确定 | MN1 State 变化频率最低，但每次变化都是 regime change |
| 逝曰远（运行不息意味着伸展到远方） | W1：周线是"势的延伸"，它把月线的大方向展开为可操作的中期趋势 | W1 把 MN1 的宏观方向"展开"为 4-8 周的趋势段 |
| 远曰反（伸展到远方意味着最终返回） | D1：日线是"返回点"，它最终会揭示趋势是否到头、是否要回归 | D1 的高频波动最先捕捉到趋势衰竭的信号 |

**落地实现：** 这个映射不只是哲学比喻，它定义了一个**因果传导链**：

```python
class CausalChain:
    """道德经因果传导链的工程实现"""
    
    def detect_regime_exhaustion(self) -> dict:
        """从D1的反向信号追溯到MN1的regime是否真的要反转"""
        
        # D1率先出现衰竭信号（远曰反）
        d1_exhaustion = self.detect_d1_exhaustion()
        # 指标：D1 State从E/F降级 + ADX拐头 + 成交量萎缩
        
        if not d1_exhaustion:
            return {"regime": "intact"}
        
        # 向上传导到W1（逝曰远——检查趋势延伸是否到头）
        w1_divergence = self.check_w1_divergence()
        # 指标：W1仍在EF但D1已经降级 = W1-D1背离
        
        if not w1_divergence:
            return {"regime": "pullback_only", "action": "hold"}
        
        # 继续向上传导到MN1（大曰逝——检查大势是否真的要反转）
        mn1_weakening = self.check_mn1_weakening()
        # 指标：MN1 ADX拐头 + MN1 close接近SR位
        
        if mn1_weakening:
            return {"regime": "reversal_likely", "action": "reduce_all"}
        else:
            return {"regime": "correction_in_trend", "action": "buy_dip_on_d1_recovery"}
```

这就是"反者道之动"的工程化：D1 的反向信号不是孤立事件，它必须沿因果链向上传导，只有传导到 MN1 才是真正的 regime 变化。

### 风险与盲点

哲学映射的风险在于"强行对应"。道德经的"反"不一定等于"趋势反转"——它可能指均值回归，也可能指周期性波动。工程实现中必须区分这两种情况（均值回归 = D1 短暂降级后恢复；周期波动 = W1 也降级但 MN1 不变）。

### 与其他答案的关系

与 Q2（三周期权重）共识：因果传导链定义了三个周期的信息传导方向（D1→W1→MN1），权重分配应该尊重这个传导方向。与 Q7（收缩观测）共识："大曰逝"对应的 MN1 收缩态变化，是整个系统最重要的宏观信号。

---

## Q6 强化学习的因子体系

### 判断

分为三层：必需因子层（人工定义，确定性计算）、自发现因子层（算法挖掘）、权重自修正层（在线学习）。

### 推理链

#### 第一层：必需因子（人工定义）

这些是已知的、有经济学意义的因子，必须硬编码：

```python
REQUIRED_FACTORS = {
    # ── 时间因子 ──
    "season": {
        "type": "categorical",
        "values": ["spring_rally", "summer_doldrums", "autumn_harvest", "year_end"],
        "mapping": {1: "spring_rally", 2: "spring_rally", 3: "spring_rally",
                    4: "summer_doldrums", 5: "summer_doldrums", 6: "summer_doldrums",
                    7: "summer_doldrums", 8: "summer_doldrums", 9: "autumn_harvest",
                    10: "autumn_harvest", 11: "autumn_harvest", 12: "year_end"},
        "rationale": "A股春季躁动、夏季缩量、秋季收获、年末结账的季节效应"
    },
    "solar_term": {
        "type": "categorical",
        "values": 24节气,
        "rationale": "节气与农业/消费/政策周期相关，A股有统计显著的节气效应"
    },
    "weekday": {
        "type": "categorical",
        "values": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        "rationale": "周一效应、周五效应在A股有文献支持"
    },
    "month_end": {
        "type": "binary",
        "rationale": "月末资金面紧张，机构调仓"
    },
    
    # ── 事件因子 ──
    "earnings_window": {
        "type": "continuous",  # 距财报发布日天数（负=预期，正=已发布）
        "rationale": "财报季效应"
    },
    "policy_meeting": {
        "type": "binary",  # 是否在重大会议前后5天窗口
        "events": ["两会", "政治局会议", "央行议息", "经济工作会议"],
        "rationale": "政策预期与维稳效应"
    },
    "index_rebalance": {
        "type": "binary",
        "rationale": "沪深300/中证500成分股调整效应"
    },
    
    # ── 市场微观结构因子 ──
    "northbound_flow_zscore": {
        "type": "continuous",
        "rationale": "北向资金20日z-score"
    },
    "margin_balance_delta": {
        "type": "continuous",
        "rationale": "融资余额变化率"
    },
    "limit_up_down_ratio": {
        "type": "continuous",
        "rationale": "涨停/跌停比，衡量市场极端情绪"
    },
    
    # ── State因子（系统内生）──
    "state_transition_direction": {
        "type": "categorical",  # upgrading/stable/downgrading
        "rationale": "State迁移方向"
    },
    "market_phase": {
        "type": "categorical",  # contraction/emergence/progression/extension/risk_release
        "rationale": "市场相"
    },
    "industry_ef2_rate": {
        "type": "continuous",
        "rationale": "行业EF2率"
    },
}
```

#### 第二层：因子自发现算法

```python
class FactorAutoDiscovery:
    """基于特征工程的因子自发现"""
    
    def discover(self, foundation_db: DuckDB, forward_returns: pd.Series) -> list[FactorCandidate]:
        candidates = []
        
        # 方法1：State组合爆炸 + 统计检验
        # 穷举所有有意义的State组合，测试其与前瞻收益的关系
        state_combos = self.enumerate_state_combos(
            periods=["mn1", "w1", "d1"],
            min_periods_with_ef=1,
            max_periods_with_ef=3
        )
        for combo in state_combos:
            t_stat, p_value = self.ttest_forward_return(foundation_db, combo, forward_returns)
            if p_value < 0.01 and abs(t_stat) > 2.5:
                candidates.append(FactorCandidate(
                    name=f"state_combo_{combo}",
                    t_stat=t_stat,
                    p_value=p_value,
                    sample_size=self.count_samples(foundation_db, combo)
                ))
        
        # 方法2：时间窗口扫描
        # 对每个连续变量因子，扫描最优的lookback窗口
        for factor_name in self.continuous_factors:
            for window in [5, 10, 20, 60, 120]:
                zscore = self.compute_zscore(foundation_db, factor_name, window)
                corr = zscore.corr(forward_returns)
                if abs(corr) > 0.05:  # 门槛可调
                    candidates.append(FactorCandidate(
                        name=f"{factor_name}_z{window}",
                        correlation=corr,
                        window=window
                    ))
        
        # 方法3：交叉因子挖掘
        # 两个因子的交互项是否比单独更好
        for f1, f2 in combinations(self.top_factors, 2):
            interaction = f1 * f2
            improvement = self.compare_with_interaction(f1, f2, interaction, forward_returns)
            if improvement > 0.02:  # R²提升超过2%
                candidates.append(FactorCandidate(
                    name=f"{f1.name}_x_{f2.name}",
                    r_squared_improvement=improvement
                ))
        
        # 多重检验校正（Bonferroni或FDR）
        return self.fdr_correction(candidates, alpha=0.05)
```

#### 第三层：权重自修正机制

```python
class WeightSelfCorrection:
    """基于Exponential Weighted Moving Average的在线权重修正"""
    
    def __init__(self, initial_weights: dict, learning_rate: float = 0.05):
        self.weights = initial_weights.copy()
        self.lr = learning_rate
        self.performance_history = deque(maxlen=60)  # 60天窗口
    
    def update(self, factor_contributions: dict, actual_return: float):
        """每天收盘后更新一次"""
        self.performance_history.append({
            "date": today(),
            "contributions": factor_contributions,
            "actual": actual_return
        })
        
        # 计算每个因子的滚动贡献度
        for factor_name in self.weights:
            # 方法：该因子预测方向与实际方向的吻合度
            accuracy = self.compute_rolling_accuracy(factor_name, window=20)
            
            # 梯度方向：如果准确度高，增加权重；反之减少
            gradient = accuracy - 0.5  # 以50%为基准
            self.weights[factor_name] += self.lr * gradient
            
            # 约束：权重不能为负，总和归一化
            self.weights[factor_name] = max(0.01, self.weights[factor_name])
        
        # 归一化
        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}
        
        # 安全检查：单个因子权重不超过40%
        for k in self.weights:
            if self.weights[k] > 0.40:
                self.weights[k] = 0.40
                # 重新归一化其余因子
    
    def detect_regime_change(self) -> bool:
        """如果因子权重在过去30天变化超过50%，标记regime change"""
        if len(self.performance_history) < 30:
            return False
        old_weights = self.compute_average_weights(window_start=-60, window_end=-30)
        new_weights = self.compute_average_weights(window_start=-30, window_end=0)
        max_change = max(abs(new_weights[k] - old_weights[k]) / old_weights[k] 
                        for k in old_weights)
        return max_change > 0.5
```

### 风险与盲点

因子自发现最大的风险是**多重比较问题（multiple comparisons）**。如果你测试了 1000 个因子组合，在 α=0.05 下会有 50 个假阳性。必须用 FDR（False Discovery Rate）校正。另外，A 股数据历史短（只有约 20 年日线数据），因子发现的统计功效（power）有限，容易出现过拟合。

### 与其他答案的关系

与 Q2（三周期权重）共识：权重自修正机制最终会告诉我们三周期的"真实"权重应该是多少。与 Q9（量变到质变）共识：regime change 检测就是质变的一种统计确认方法。

---

## Q7 收缩观测体系

### 判断

收缩→突破→质变的量化需要三个独立指标交叉验证，突破确认需要**至少 2/3 指标同时确认**。

### 推理链

当前系统已有布林带宽（BB）作为收缩指标（在 State 编码中 base=0 代表收缩），但缺少系统性的多维度收缩观测。

**三个核心指标：**

```python
class ContractionObserver:
    """多周期收缩观测器"""
    
    def compute_contraction_metrics(self, symbol: str, period: str) -> ContractionMetrics:
        ohlcv = self.get_ohlcv(symbol, period)
        
        # 指标1：布林带宽（BB Width Ratio）
        # 多窗口：BB20/BB50/BB100
        bb20_width = (bb_upper(ohlcv, 20) - bb_lower(ohlcv, 20)) / bb_mid(ohlcv, 20)
        bb50_width = (bb_upper(ohlcv, 50) - bb_lower(ohlcv, 50)) / bb_mid(ohlcv, 50)
        bb100_width = (bb_upper(ohlcv, 100) - bb_lower(ohlcv, 100)) / bb_mid(ohlcv, 100)
        
        # 布林带宽百分位（当前宽度在过去252天中的位置）
        bb_percentile = percentile_rank(bb20_width, history_252d)
        
        # 指标2：枢轴带宽（Pivot Width Ratio）
        # SR间距 / 当前价格
        sr_levels = self.get_sr_levels(symbol, period)
        pivot_width = (sr_levels.resistance - sr_levels.support) / ohlcv.close.iloc[-1]
        pivot_percentile = percentile_rank(pivot_width, history_252d)
        
        # 指标3：ATR比率（ATR Ratio）
        # ATR(14) / close
        atr_ratio = atr(ohlcv, 14) / ohlcv.close.iloc[-1]
        atr_percentile = percentile_rank(atr_ratio, history_252d)
        
        return ContractionMetrics(
            bb_percentile=bb_percentile,
            pivot_percentile=pivot_percentile,
            atr_percentile=atr_percentile,
            # 综合收缩分数：三个百分位的加权平均
            contraction_score=0.4 * bb_percentile + 0.35 * pivot_percentile + 0.25 * atr_percentile
        )
    
    def detect_breakout(self, symbol: str, period: str) -> BreakoutSignal:
        metrics = self.compute_contraction_metrics(symbol, period)
        ohlcv = self.get_ohlcv(symbol, period)
        
        # 突破确认条件（至少2/3满足）
        confirmations = 0
        
        # 条件1：价格突破布林带上轨 + 成交量放大
        if ohlcv.close.iloc[-1] > bb_upper(ohlcv, 20) and \
           ohlcv.volume.iloc[-1] > ohlcv.volume.rolling(20).mean().iloc[-1] * 1.5:
            confirmations += 1
        
        # 条件2：价格突破枢轴阻力位
        sr = self.get_sr_levels(symbol, period)
        if ohlcv.close.iloc[-1] > sr.resistance:
            confirmations += 1
        
        # 条件3：ATR比率从低位快速扩张（波动率突破）
        atr_ratio = atr(ohlcv, 14) / ohlcv.close.iloc[-1]
        atr_expansion = atr_ratio / atr_ratio.rolling(20).mean().iloc[-1]
        if atr_expansion > 1.5:  # ATR扩张50%以上
            confirmations += 1
        
        return BreakoutSignal(
            confirmed=confirmations >= 2,
            confirmations=confirmations,
            details={...}
        )
```

**多周期交叉验证：**

收缩突破必须在多个时间框架上同时确认才有意义：

```python
def multi_period_breakout_check(symbol: str) -> MultiPeriodBreakout:
    results = {}
    for period in ["MN1", "W1", "D1"]:
        results[period] = observer.detect_breakout(symbol, period)
    
    # 最强信号：D1突破 + W1收缩在低位（蓄势充分）+ MN1方向向上（大势支撑）
    if results["D1"].confirmed and \
       results["W1"].metrics.contraction_score < 0.3 and \
       results["MN1"].metrics.bb_percentile > 0.5:
        return MultiPeriodBreakout(grade="A", action="full_entry")
    
    # 次强信号：D1突破 + W1也在突破
    if results["D1"].confirmed and results["W1"].confirmed:
        return MultiPeriodBreakout(grade="B", action="half_entry")
    
    # 弱信号：只有D1突破
    if results["D1"].confirmed:
        return MultiPeriodBreakout(grade="C", action="watch_only")
    
    return MultiPeriodBreakout(grade="none")
```

### 风险与盲点

布林带宽、枢轴带宽、ATR比率三者高度相关（correlation 可能在 0.7 以上），这意味着"2/3确认"实际上可能约等于"1个确认"。需要做主成分分析（PCA）确认三个指标的独立信息量。如果 PCA 显示第一主成分解释了 85% 以上的方差，说明三个指标本质上是同一个东西，应该只用一个。

### 与其他答案的关系

与 Q1（产品内核）共识：收缩观测是"运转系统"的核心能力之一。与 Q5b（道德经映射）共识：MN1 的收缩态是"大曰逝"的具体量化。与 Codex-2（计算架构）直接相关：5510×3 周期的收缩指标计算需要高效的计算架构。

---

## Q8 多 Agent 体系的构建验证与运行

### Q8a 测试金字塔

```
                    ┌─────────┐
                    │ E2E测试  │  ← 全流水线端到端（每日一次）
                   ┌┴─────────┴┐
                   │ 集成测试    │  ← Agent间协作（每周一次）
                  ┌┴───────────┴┐
                  │ 单元测试      │  ← 每个Agent内部逻辑（每次代码变更）
                 ┌┴─────────────┴┐
                 │ 契约测试        │  ← Agent输入输出格式（CI/CD）
                ┌┴───────────────┴┐
                │ 快照回归测试      │  ← Foundation DB输出不变性（每次代码变更）
                └─────────────────┘
```

```python
class TestPyramid:
    # 层1：快照回归（最底层，每次commit运行）
    def test_foundation_snapshot(self):
        """给定同一天的输入数据，foundation DB的输出必须与基线快照一致"""
        baseline = load_snapshot("2026-05-20_baseline")
        actual = run_foundation_build("2026-05-20")
        assert duckdb_diff(baseline, actual).row_count == 0
    
    # 层2：契约测试（每次commit运行）
    def test_agent_contracts(self):
        """每个Agent的输入输出必须符合预定义的JSON Schema"""
        for agent in ALL_AGENTS:
            input_schema = load_schema(f"{agent.name}_input.json")
            output_schema = load_schema(f"{agent.name}_output.json")
            sample_input = generate_sample_input(agent.name)
            result = agent.process(sample_input)
            assert validate(result, output_schema)
    
    # 层3：单元测试（每次代码变更运行）
    def test_state_calculation(self):
        """State位运算的正确性"""
        # 已知输入→已知输出的确定性测试
        assert compute_state_hex(base=8, trend=1, position=2, volatility=1) == 0xF
        assert compute_state_hex(base=0, trend=0, position=0, volatility=0) == 0x0
    
    # 层4：集成测试（每周运行）
    def test_agent_collaboration(self):
        """多Agent协作链的正确性"""
        # 模拟State跳变 → 验证消息链
        event_bus.emit("state_transition", {"symbol": "000001", "from": "C", "to": "E"})
        messages = event_bus.get_messages(timeout=5)
        assert any(m.to_agent == "strategy_advisor" for m in messages)
        assert any(m.to_agent == "risk_guardian" for m in messages)
    
    # 层5：端到端测试（每日运行）
    def test_full_daily_pipeline(self):
        """完整日流水线的正确性"""
        result = run_daily_pipeline(date=today())
        assert result.foundation_db_exists
        assert result.state_cache_row_count > 5000
        assert result.observation_pool_row_count > 0
        assert result.html_output_exists
```

### Q8b 评价体系

```python
class AgentEvaluation:
    """谁评价、依据什么、什么时间"""
    
    evaluators = {
        # 自动评价（每日）
        "daily_auto": {
            "evaluator": "test_pyramid",
            "criteria": ["snapshot_regression", "contract_compliance", "output_completeness"],
            "frequency": "daily_after_pipeline",
            "action_on_fail": "block_output_and_alert"
        },
        
        # 统计评价（每周）
        "weekly_statistical": {
            "evaluator": "calibration_trigger",
            "criteria": ["forward_observation_accuracy", "signal_hit_rate", "sharpe_ratio"],
            "frequency": "weekly_friday",
            "action_on_degradation": "generate_calibration_report"
        },
        
        # 人工评审（每月）
        "monthly_human": {
            "evaluator": "human_reviewer",
            "criteria": ["strategy_pnl_attribution", "false_positive_rate", "missed_signals"],
            "frequency": "monthly_first_weekend",
            "action": "parameter_tuning_or_strategy_revision"
        },
        
        # 交叉评价（持续）
        "cross_agent": {
            "evaluator": "cognitive_detective",
            "criteria": ["agent_consistency", "contradiction_detection"],
            "frequency": "on_every_proposal",
            "action_on_contradiction": "flag_for_human_review"
        }
    }
```

### Q8c Agent 间消息总线

```python
class AgentMessageBus:
    """轻量消息总线：基于DuckDB + 文件锁的实现"""
    # 选择DuckDB而非Redis的原因：
    # 1. 系统已经大量使用DuckDB，不引入新依赖
    # 2. 消息需要持久化用于审计
    # 3. 消息量不大（每天几百条），不需要Redis的性能
    
    def __init__(self, db_path: str):
        self.conn = duckdb.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id VARCHAR PRIMARY KEY,
                from_agent VARCHAR NOT NULL,
                to_agent VARCHAR NOT NULL,
                message_type VARCHAR NOT NULL,
                payload JSON NOT NULL,
                confidence DOUBLE,
                status VARCHAR DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT current_timestamp,
                processed_at TIMESTAMP,
                ttl_seconds INTEGER DEFAULT 3600
            )
        """)
    
    def send(self, message: AgentMessage):
        self.conn.execute(
            "INSERT INTO agent_messages VALUES (?, ?, ?, ?, ?, ?, 'pending', current_timestamp, NULL, ?)",
            [message.id, message.from_agent, message.to_agent, 
             message.message_type, json.dumps(message.payload), 
             message.confidence, message.ttl_seconds]
        )
    
    def receive(self, agent_name: str) -> list[AgentMessage]:
        messages = self.conn.execute("""
            SELECT * FROM agent_messages 
            WHERE to_agent = ? AND status = 'pending' 
            AND created_at > current_timestamp - INTERVAL (ttl_seconds || ' seconds')
            ORDER BY created_at
        """, [agent_name]).fetchall()
        
        # 标记为已处理
        for msg in messages:
            self.conn.execute(
                "UPDATE agent_messages SET status = 'processed', processed_at = current_timestamp WHERE id = ?",
                [msg[0]]
            )
        return messages
```

### Q8d 持续运行与降级

```python
class GracefulDegradation:
    """Assume Failure 降级路径"""
    
    DEGRADATION_LEVELS = {
        0: "FULL_OPERATION",      # 所有Agent正常
        1: "REDUCED_CONFIDENCE",  # 部分Agent降级，信号置信度打折
        2: "CORE_ONLY",           # 只运行核心流水线，Agent协作停止
        3: "READ_ONLY",           # 只展示数据，不生成信号
        4: "CIRCUIT_BREAKER",     # 全停，等待人工介入
    }
    
    def __init__(self):
        self.current_level = 0
        self.agent_health = {}
    
    def check_agent_health(self, agent_name: str) -> AgentHealth:
        """检查Agent健康状态"""
        try:
            # 心跳检查：Agent能否在5秒内响应
            start = time.time()
            result = agent_name.ping()
            latency = time.time() - start
            
            if latency > 5.0:
                return AgentHealth(status="degraded", latency=latency)
            if result.is_valid():
                return AgentHealth(status="healthy", latency=latency)
            return AgentHealth(status="error", error="invalid_response")
        except Exception as e:
            return AgentHealth(status="down", error=str(e))
    
    def update_system_level(self):
        """根据Agent健康状况更新系统降级级别"""
        healths = {name: self.check_agent_health(name) for name in ALL_AGENTS}
        
        down_agents = [n for n, h in healths.items() if h.status == "down"]
        degraded_agents = [n for n, h in healths.items() if h.status == "degraded"]
        
        # 核心Agent列表
        core_agents = ["market_analyst", "risk_guardian"]
        
        if any(a in core_agents for a in down_agents):
            self.current_level = 3  # 核心Agent挂了 → READ_ONLY
        elif len(down_agents) >= 3:
            self.current_level = 2  # 3个以上Agent挂了 → CORE_ONLY
        elif len(down_agents) >= 1 or len(degraded_agents) >= 3:
            self.current_level = 1  # 部分降级 → REDUCED_CONFIDENCE
        else:
            self.current_level = 0  # 全正常
        
        if self.current_level >= 3:
            self.send_alert("系统降级至Level 3，请人工介入")
```

### 风险与盲点

DuckDB 作为消息总线的风险是**并发写入冲突**。如果多个 Agent 同时写入同一个 DuckDB 文件，可能遇到锁争用。缓解方案：每个 Agent 写自己的 WAL 文件，由一个中央 collector 定期合并。或者升级为 SQLite（更好的并发写支持）或 Redis（如果消息量增长）。

### 与其他答案的关系

与 Q4（Agent 自组织）强耦合：自组织 Agent 的消息量远大于查询型 Agent，消息总线需要相应扩展。与 Codex-3（降级路径）直接相关：这里的降级框架需要具体的错误隔离机制（见 Codex-3）。

---

## Q9 量变到质变

### 判断

质变有三种类型，每种有不同的触发条件和统计检验方法。

### 推理链

**类型 1：市场相质变（Market Regime Change）**

从一种市场相切换到另一种（如从 contraction 到 emergence）。

```python
class MarketRegimeChangeDetector:
    def detect(self, daily_metrics: list[DailyMetrics]) -> RegimeChangeSignal:
        # 指标向量：[pool_size, volatility_distribution, state_transition_entropy, sector_dispersion]
        current_vector = self.compute_metric_vector(daily_metrics[-5:])
        baseline_vector = self.compute_metric_vector(daily_metrics[-60:-5])
        
        # Hotelling's T² 检验：当前5天的指标向量是否与过去60天有统计显著差异
        t_squared = hotelling_t2_test(current_vector, baseline_vector)
        p_value = t_squared_to_p(t_squared, df1=4, df2=55)
        
        if p_value < 0.01:
            # 确认质变：不仅统计显著，还要实际显著（effect size）
            effect_size = compute_cohens_d(current_vector, baseline_vector)
            if effect_size > 1.0:  # Cohen's d > 1 = 大效应
                return RegimeChangeSignal(
                    confirmed=True,
                    from_phase=self.classify(baseline_vector),
                    to_phase=self.classify(current_vector),
                    p_value=p_value,
                    effect_size=effect_size
                )
        return RegimeChangeSignal(confirmed=False)
```

**类型 2：策略有效性量变到质变**

一个策略的命中率逐渐下降，从"有效"变为"失效"。

```python
class StrategyDegradationDetector:
    def detect(self, strategy: str, forward_ledger: ForwardLedger) -> DegradationSignal:
        # 取最近60个信号和之前60个信号
        recent = forward_ledger.get_signals(strategy, n=60, order="desc")
        earlier = forward_ledger.get_signals(strategy, n=60, offset=60, order="desc")
        
        recent_hit_rate = recent.mean_return > 0
        earlier_hit_rate = earlier.mean_return > 0
        
        # Fisher精确检验：两个命中率是否来自同一分布
        contingency_table = [
            [sum(recent_hit_rate), len(recent_hit_rate) - sum(recent_hit_rate)],
            [sum(earlier_hit_rate), len(earlier_hit_rate) - sum(earlier_hit_rate)]
        ]
        odds_ratio, p_value = fisher_exact(contingency_table)
        
        if p_value < 0.05 and odds_ratio < 0.5:
            return DegradationSignal(
                strategy=strategy,
                confirmed=True,
                hit_rate_decline=f"{earlier_hit_rate.mean():.1%} → {recent_hit_rate.mean():.1%}",
                p_value=p_value,
                recommendation="trigger_calibration"
            )
        return DegradationSignal(confirmed=False)
```

**类型 3：Agent 体系自组织能力的质变**

系统从"被动响应"变为"主动发现"的能力跃迁。这很难用传统统计检验，但可以用一个代理指标：

```python
class SelfOrganizationMaturity:
    def assess(self, agent_proposals: list[AgentProposal], human_feedback: list[HumanFeedback]) -> MaturityScore:
        # 代理指标：Agent自主提案的被采纳率
        adoption_rate = sum(1 for f in human_feedback if f.adopted) / len(human_feedback)
        
        # 提案质量趋势：采纳的提案的平均PnL贡献
        adopted_pnl = [f.pnl_contribution for f in human_feedback if f.adopted]
        pnl_trend = linear_regression_slope(adopted_pnl)
        
        # 提案多样性：Agent是否只产生一种类型的提案
        proposal_types = Counter(p.proposal_type for p in agent_proposals)
        diversity = shannon_entropy(proposal_types)
        
        # 成熟度分数
        maturity = 0.4 * adoption_rate + 0.4 * (pnl_trend > 0) + 0.2 * (diversity > 1.0)
        
        # 质变阈值：连续90天maturity > 0.7
        return MaturityScore(
            score=maturity,
            qualitative_transition=maturity > 0.7 and self.consecutive_days_above(maturity, 0.7, 90)
        )
```

### 风险与盲点

最大的风险是**把统计噪声当作质变**。Hotelling's T² 检验假设多元正态分布，市场数据通常不满足这个假设。需要用非参数检验（如 permutation test）作为补充确认。另外，"质变"的 effect size 阈值（Cohen's d > 1.0）需要根据历史数据回测校准，不能拍脑袋定。

### 与其他答案的关系

与 Q6（因子体系）共识：regime change detection 的指标向量就是因子体系的一部分。与 Q4（Agent 自组织）共识：Agent 自组织成熟度评估是 Q4 阶段验证的基础。

---

## Q10 外部方案对标

### 判断

四个方案中，两个可以直接引入，两个需要改造。

### 逐一分析

#### 1. NousResearch/hermes-agent → 改造后引入

hermes-agent 的核心能力：自学习循环 + Skill 自动创建 + 子 Agent 委托。

**可直接引入的部分：**
- **子 Agent 委托模式（delegation pattern）**：hermes-agent 允许主 Agent 将子任务委托给子 Agent，子 Agent 独立运行并返回结果。这直接对应 Hermass 的 Agent 协作需求。实现方式：在 `AgentMessage` 中增加 `delegation_id` 字段，支持链式委托。
- **Skill 自动创建**：hermes-agent 可以根据执行经验自动创建新的 Skill。对应 Hermass：当 Agent 发现某种分析模式被反复使用时，自动封装为 Skill。

**需要改造的部分：**
- **自学习循环**：hermes-agent 的自学习是通用的（适用于各种 AI 任务），但 Hermass 的"学习"必须是受约束的——策略参数只能通过 walk-forward 验证后修改，不能自由演化。需要在自学习循环中加入"金融约束层"（financial constraint layer），确保任何参数修改都经过统计显著性检验。

#### 2. agentmemory（BM25+Vector+Graph 混合检索）→ 直接引入

**可直接引入的原因：**
- Hermass 的 `forward_observation_ledger` 已经有 191+ 样本，未来会增长到数千条。检索"历史上类似情况发生了什么"是核心需求。
- BM25 适合精确关键词检索（如"半导体 + EF + VCP"），Vector 适合语义相似性检索（如"类似于2024年9月的市场状态"），Graph 适合关系检索（如"哪些股票与宁德时代的 State 迁移模式相似"）。
- 置信度评分直接对应系统的 `confidence` 字段。

**实现方案：**
```python
class HybridMemory:
    def __init__(self):
        self.bm25 = BM25Index()          # 精确检索
        self.vector = FAISSIndex(dim=768) # 语义检索（sentence-transformer）
        self.graph = NetworkXGraph()      # 关系检索
    
    def query(self, query_text: str, query_type: str = "hybrid") -> list[MemoryResult]:
        if query_type == "exact":
            return self.bm25.search(query_text, top_k=10)
        elif query_type == "semantic":
            embedding = self.embed(query_text)
            return self.vector.search(embedding, top_k=10)
        elif query_type == "relational":
            entities = self.extract_entities(query_text)
            return self.graph.neighborhood_search(entities, depth=2)
        else:  # hybrid
            results = []
            results.extend(self.bm25.search(query_text, top_k=5))
            results.extend(self.vector.search(self.embed(query_text), top_k=5))
            results.extend(self.graph.neighborhood_search(self.extract_entities(query_text), depth=1))
            return self.deduplicate_and_rank(results)
```

#### 3. Harness Engineering（OpenAI 0行手写代码方法论）→ 改造后引入

**核心理念：** 通过声明式配置和 AI 生成代码来消除手写代码。

**可直接引入的部分：**
- **声明式工作流定义**：当前系统已经有 `agently_a_share_flow.py` 和 `agently_daily_flow.py` 两个 DAG，可以进一步将 Agent 行为也声明式化。
- **AI 生成的 SQL 查询**：让 Agent 根据用户问题自动生成 DuckDB SQL，而不是硬编码查询。

**需要改造的部分：**
- "0行手写代码"在金融系统中不完全适用。核心计算（State 编码、SR 计算、ATR）必须是确定性的、可审计的、版本控制的。可以让 AI 生成胶水代码，但核心金融逻辑必须人工编写和审核。

#### 4. Karpathy Wiki+Obsidian（三层架构+渐进式披露）→ 直接引入

**三层架构：**
- **Layer 1: 摘要层**（用户看到的首页）→ 对应 Q1 中的市场相指示器 + 热力矩阵
- **Layer 2: 详情层**（点击后展开）→ 对应行业排名 + 个股列表 + 策略信号
- **Layer 3: 原始数据层**（深度钻取）→ 对应 Foundation DB 的原始数据 + 计算过程

**渐进式披露的实现：**
```python
class ProgressiveDisclosure:
    def get_market_view(self, depth: int = 1) -> dict:
        if depth == 1:
            # 摘要：市场相 + 一句话 + 3个数字
            return {
                "phase": current_market_phase(),
                "summary": generate_one_liner(),
                "key_metrics": {
                    "ef2_count": count_ef2_stocks(),
                    "pool_change": pool_change_rate(),
                    "risk_grade": risk_guardian.grade()
                }
            }
        elif depth == 2:
            # 详情：行业排名 + 策略信号 + 前向观察
            return {
                "industry_ranking": get_industry_ranking(),
                "strategy_signals": get_all_strategy_signals(),
                "forward_summary": get_forward_observation_summary()
            }
        elif depth == 3:
            # 原始数据：DuckDB查询接口
            return {
                "query_endpoint": "/api/query",
                "schema": get_foundation_schema(),
                "sample_data": get_sample_rows(10)
            }
```

### 风险与盲点

引入外部方案的最大风险是**架构复杂度爆炸**。每引入一个新组件都增加运维负担。建议优先级：agentmemory（最实用）> Karpathy 三层架构（改善用户体验）> hermes-agent delegation（增强 Agent 协作）> Harness Engineering（长期效率）。

### 与其他答案的关系

与 Q4（Agent 自组织）共识：hermes-agent 的 delegation pattern 是阶段 2 的技术基础。与 Q8（构建验证）共识：引入新组件需要扩展测试金字塔。

---

## Codex-2 收缩观测 Agent 计算架构

### 判断

最优方案是**DuckDB 预计算 + 增量更新**，不是物化视图（DuckDB 的物化视图支持有限）。

### 推理链

**计算量估算：**

```
5510 股票 × 3 周期（MN1/W1/D1）× 3 指标（BB/Pivot/ATR）
= 5510 × 3 × 3 = 49,590 个指标计算

每个指标需要：
- BB(20): 20天OHLCV → rolling std → 1次计算
- BB(50): 50天OHLCV → rolling std → 1次计算
- BB(100): 100天OHLCV → rolling std → 1次计算
- Pivot: SR读取 + 除法 → 1次计算
- ATR(14): 14天TR → rolling mean → 1次计算

总计：5510 × 3 × 5 = 82,650 次滚动计算/天
```

**但实际计算量远小于此，因为增量特性：**
- 每天只有 D1 数据更新（MN1 每月更新一次，W1 每周更新一次）
- D1 的 BB/ATR 只需要追加一天的数据，不需要重算历史
- 只有新进入观察池的股票需要计算全部历史百分位

**最优架构：**

```python
class ContractionComputeEngine:
    """收缩指标计算引擎"""
    
    def __init__(self, foundation_db_path: str):
        self.conn = duckdb.connect(foundation_db_path)
        self.cache_dir = "outputs/contraction_cache"
    
    def daily_update(self, date: str):
        """每日增量更新"""
        
        # 第一步：只更新D1周期的指标（MN1/W1不需要每日更新）
        # 使用DuckDB的window function一次性计算所有股票的D1指标
        self.conn.execute(f"""
            CREATE OR REPLACE TABLE contraction_d1_{date} AS
            SELECT
                symbol,
                date,
                -- BB Width (多窗口)
                (bb_upper_20 - bb_lower_20) / bb_mid_20 AS bb_width_20,
                (bb_upper_50 - bb_lower_50) / bb_mid_50 AS bb_width_50,
                (bb_upper_100 - bb_lower_100) / bb_mid_100 AS bb_width_100,
                -- ATR Ratio
                atr_14 / close AS atr_ratio,
                -- Pivot Width（从SR表join）
                (sr.resistance - sr.support) / close AS pivot_width
            FROM ohlcv_d1
            JOIN sr_levels_d1 USING (symbol, date)
            WHERE date = '{date}'
        """)
        
        # 第二步：计算百分位（需要历史数据，但用增量方式）
        # 关键优化：百分位不需要每天重算全部历史
        # 只需要把新值插入已排序的历史数组中，用bisect找到位置
        self.compute_percentiles_incremental(date)
        
        # 第三步：MN1只在月初更新，W1只在周一更新
        day_of_week = get_day_of_week(date)
        day_of_month = get_day_of_month(date)
        
        if day_of_week == 0:  # 周一
            self.update_period("W1", date)
        if day_of_month == 1:  # 月初（或第一个交易日）
            self.update_period("MN1", date)
    
    def compute_percentiles_incremental(self, date: str):
        """增量百分位计算"""
        # 从缓存加载前一天的百分位历史
        prev_cache = self.load_cache(date, offset=-1)
        
        # 对每只股票，用bisect插入新值
        new_percentiles = {}
        for symbol in self.all_symbols:
            new_bb = self.get_bb_width(symbol, date)
            historical_bbs = prev_cache.get_bb_history(symbol)
            
            # bisect插入 → O(log n) 而非 sort → O(n log n)
            import bisect
            pos = bisect.bisect_left(historical_bbs, new_bb)
            percentile = pos / len(historical_bbs)
            
            new_percentiles[symbol] = percentile
        
        # 写入缓存
        self.save_cache(date, new_percentiles)
    
    def batch_query(self, symbols: list[str], date: str) -> pd.DataFrame:
        """批量查询（供Agent使用）"""
        return self.conn.execute(f"""
            SELECT symbol, bb_percentile, pivot_percentile, atr_percentile,
                   contraction_score
            FROM contraction_cache
            WHERE date = '{date}' AND symbol IN ({','.join(f"'{s}'" for s in symbols)})
        """).fetchdf()
```

**性能估算：**

```
每日D1增量计算：
- 5510只股票 × 5个rolling指标 = 27,550次计算
- DuckDB的向量化执行：约 2-5 秒

增量百分位（bisect）：
- 5510次 bisect_left = O(5510 × log(252)) ≈ O(44,000) 比较操作
- 约 0.1 秒

MN1月度更新（5510只股票）：约 1-2 秒
W1周度更新（5510只股票）：约 1-2 秒

总计：每日常规更新 < 10秒
```

**为什么不用 DuckDB 物化视图：**
DuckDB 的物化视图（截至当前版本）不支持增量刷新（incremental refresh），每次查询都会完全重算。对于 5510 只股票 × 252 天历史的 rolling 计算，全量重算需要 30-60 秒，不可接受。自定义的增量缓存方案更优。

### 风险与盲点

缓存一致性风险：如果某天 D1 数据下载失败但缓存已经写入，会导致脏数据。解决方案：所有缓存写入在一个事务中完成，失败时自动回滚。

### 与其他答案的关系

与 Q7（收缩观测）直接相关：这是收缩观测体系的计算底座。与 Q4（Agent 自组织）相关：Agent 需要实时访问收缩指标，计算延迟必须 < 10 秒。

---

## Codex-3 Assume Failure 降级路径——错误隔离与恢复

### 判断

错误隔离的核心原则是**舱壁模式（Bulkhead Pattern）**：每个 Agent 运行在独立的资源边界中，一个 Agent 的故障不能消耗其他 Agent 的资源。

### 推理链

```python
class AgentIsolationFramework:
    """舱壁模式实现"""
    
    class AgentContainer:
        """每个Agent的隔离容器"""
        def __init__(self, agent_name: str, timeout: float, max_retries: int):
            self.agent_name = agent_name
            self.timeout = timeout
            self.max_retries = max_retries
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=3,     # 连续3次失败触发熔断
                recovery_timeout=300,    # 熔断后5分钟尝试恢复
                half_open_max_calls=1    # 恢复时只允许1个试探调用
            )
            self.fallback = None
        
        def execute(self, context: AgentContext) -> AgentResult:
            # 第一层：熔断器保护
            if self.circuit_breaker.is_open():
                return self.get_fallback_result(context, reason="circuit_breaker_open")
            
            # 第二层：超时保护
            try:
                result = self.execute_with_timeout(context, self.timeout)
                self.circuit_breaker.record_success()
                return result
            except TimeoutError:
                self.circuit_breaker.record_failure()
                return self.get_fallback_result(context, reason="timeout")
            except Exception as e:
                self.circuit_breaker.record_failure()
                # 第三层：重试保护
                if self.circuit_breaker.failure_count < self.max_retries:
                    return self.execute(context)  # 递归重试（最多max_retries次）
                return self.get_fallback_result(context, reason=f"error: {e}")
        
        def execute_with_timeout(self, context: AgentContext, timeout: float) -> AgentResult:
            """用subprocess隔离执行，防止资源泄漏"""
            import subprocess
            import json
            
            # 将context序列化到临时文件
            ctx_file = f"/tmp/agent_{self.agent_name}_ctx.json"
            with open(ctx_file, 'w') as f:
                json.dump(context.to_dict(), f)
            
            # 在子进程中执行
            proc = subprocess.Popen(
                [sys.executable, "-m", f"agents.{self.agent_name}", ctx_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                if proc.returncode != 0:
                    raise RuntimeError(f"Agent exited with code {proc.returncode}: {stderr.decode()}")
                return AgentResult.from_json(stdout.decode())
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise TimeoutError(f"Agent {self.agent_name} timed out after {timeout}s")
        
        def get_fallback_result(self, context: AgentContext, reason: str) -> AgentResult:
            """降级结果：返回缓存的最近一次成功结果，或空结果"""
            cached = self.load_last_successful_result()
            if cached and not cached.is_stale(max_age=3600):
                return AgentResult(
                    data=cached.data,
                    confidence=cached.confidence * 0.5,  # 降级时置信度打折
                    metadata={"fallback": True, "reason": reason}
                )
            return AgentResult(
                data=None,
                confidence=0.0,
                metadata={"fallback": True, "reason": reason, "no_cache": True}
            )
    
    class CircuitBreaker:
        """熔断器：防止级联故障"""
        def __init__(self, failure_threshold: int, recovery_timeout: float, half_open_max_calls: int):
            self.failure_threshold = failure_threshold
            self.recovery_timeout = recovery_timeout
            self.half_open_max_calls = half_open_max_calls
            self.failure_count = 0
            self.state = "CLOSED"  # CLOSED → OPEN → HALF_OPEN → CLOSED
            self.last_failure_time = None
            self.half_open_calls = 0
        
        def is_open(self) -> bool:
            if self.state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.half_open_calls = 0
                    return False
                return True
            return False
        
        def record_success(self):
            self.failure_count = 0
            self.state = "CLOSED"
        
        def record_failure(self):
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
```

**级联故障防护的完整链路：**

```python
class CascadeFailurePrevention:
    """防止Agent故障级联"""
    
    def __init__(self, agents: dict[str, AgentContainer]):
        self.agents = agents
        self.dependency_graph = {
            # 定义Agent间的依赖关系
            "market_analyst": [],              # 无依赖
            "contraction_observer": [],         # 无依赖
            "risk_guardian": ["market_analyst"],  # 依赖market_analyst
            "strategy_advisor": ["market_analyst", "risk_guardian"],
            "cognitive_detective": ["strategy_advisor"],
            "coach": [],                        # 无依赖
            "monetization_butler": ["strategy_advisor", "risk_guardian"],
        }
    
    def execute_pipeline(self, context: AgentContext) -> PipelineResult:
        """按依赖拓扑序执行，跳过故障Agent的下游"""
        results = {}
        failed_agents = set()
        
        # 拓扑排序
        execution_order = topological_sort(self.dependency_graph)
        
        for agent_name in execution_order:
            # 检查依赖是否都健康
            deps = self.dependency_graph[agent_name]
            failed_deps = [d for d in deps if d in failed_agents]
            
            if failed_deps:
                # 有依赖故障 → 该Agent也降级
                results[agent_name] = AgentResult(
                    data=None,
                    confidence=0.0,
                    metadata={
                        "skipped": True,
                        "reason": f"dependency_failed: {failed_deps}"
                    }
                )
                failed_agents.add(agent_name)
                continue
            
            # 执行Agent
            result = self.agents[agent_name].execute(context)
            results[agent_name] = result
            
            if result.is_failure():
                failed_agents.add(agent_name)
        
        return PipelineResult(
            results=results,
            degraded_agents=failed_agents,
            system_level=self.compute_system_level(failed_agents)
        )
    
    def compute_system_level(self, failed_agents: set) -> int:
        """计算系统降级级别"""
        critical_agents = {"market_analyst", "risk_guardian"}
        
        if critical_agents & failed_agents:
            return 3  # READ_ONLY
        elif len(failed_agents) >= len(self.agents) * 0.5:
            return 2  # CORE_ONLY
        elif len(failed_agents) > 0:
            return 1  # REDUCED_CONFIDENCE
        return 0  # FULL_OPERATION
```

**恢复机制：**

```python
class AgentRecovery:
    """Agent恢复策略"""
    
    def attempt_recovery(self, agent_name: str) -> RecoveryResult:
        container = self.agents[agent_name]
        
        # 策略1：重启Agent进程
        try:
            container.restart()
            health = container.health_check()
            if health.status == "healthy":
                return RecoveryResult(success=True, strategy="restart")
        except Exception:
            pass
        
        # 策略2：清理Agent缓存后重启
        try:
            container.clear_cache()
            container.restart()
            health = container.health_check()
            if health.status == "healthy":
                return RecoveryResult(success=True, strategy="clear_cache_restart")
        except Exception:
            pass
        
        # 策略3：降级为只读模式（使用缓存数据）
        container.enable_readonly_mode()
        return RecoveryResult(
            success=False,
            strategy="readonly_fallback",
            message=f"Agent {agent_name} 进入只读模式，使用缓存数据"
        )
    
    def schedule_periodic_recovery(self):
        """定期尝试恢复故障Agent"""
        for agent_name, container in self.agents.items():
            if container.circuit_breaker.state == "OPEN":
                result = self.attempt_recovery(agent_name)
                if result.success:
                    container.circuit_breaker.reset()
                    log(f"Agent {agent_name} 恢复成功，策略: {result.strategy}")
```

**核心设计原则总结：**

1. **进程隔离**：每个 Agent 在独立子进程中运行，一个 Agent 的 OOM/死循环不会拖垮其他 Agent。
2. **熔断器**：连续 3 次失败自动熔断，5 分钟后试探恢复，防止"反复尝试失败操作"的恶性循环。
3. **超时保护**：每个 Agent 有独立超时，超时后强制 kill 进程。
4. **依赖感知降级**：如果上游 Agent 故障，下游 Agent 自动跳过而非等待，避免线程池耗尽。
5. **缓存降级**：故障 Agent 返回上一次成功结果的降级版本（置信度打折），而非完全空白。
6. **定期恢复**：后台线程定期尝试恢复故障 Agent，不需要人工干预。

### 风险与盲点

子进程隔离的代价是**启动延迟**（Python 进程启动约 0.5-1 秒）。对于需要快速响应的 Agent（如 risk_guardian），可能需要在进程池中预热。另外，如果所有 Agent 同时故障（如 DuckDB 文件损坏），级联降级会直接跳到 Level 3 READ_ONLY，这时需要人工介入修复数据库。

---

## 矛盾与共识总览

| 问题对 | 关系类型 | 说明 |
|--------|----------|------|
| Q2 ↔ Q3 | 矛盾（已解决） | 两个"否决票"叠加导致信号过少 → 采用"双否才否决"规则 |
| Q1 ↔ Q4 | 共识 | "运转系统"定位是自组织 Agent 的前提 |
| Q2 ↔ Q5b | 共识 | 因果传导链定义了三周期的信息流向 |
| Q6 ↔ Q9 | 共识 | regime change detection 是两者的交汇点 |
| Q7 ↔ Codex-2 | 直接依赖 | 收缩观测的计算架构支撑收缩指标 |
| Q8 ↔ Codex-3 | 直接依赖 | 降级路径是构建验证的一部分 |
| Q4 ↔ Q10 | 共识 | hermes-agent delegation 是 Agent 自组织的技术基础 |
| Q3 ↔ Q2 | 部分矛盾 | 行业门控与MN1门控的叠加问题 |

---

> 以上分析基于 2026-06-01 的代码库状态。所有工程方案均为初版设计，需经 walk-forward 验证后方可投产。
