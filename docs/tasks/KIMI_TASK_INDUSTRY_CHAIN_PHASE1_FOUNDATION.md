# Kimi 任务：产业链栏目 Phase 1 — 数据底座 + /chain-studio 骨架

> 发件人：Claude  
> 日期：2026-06-06  
> 前置条件：已确认 `KIMI_TASK_INDUSTRY_CHAIN_DUAL_TRACK_ROLLOUT.md` 全部约束  
> 对应文档：`docs/INDUSTRY_CHAIN_IMPLEMENTATION_PLAYBOOK_20260606.md`

---

## 一、目标

让 `/chain-studio` 能打开、能读到真实数据、能展示 P0 三条链的最小热力总览。同时 `/chain-assistant` 保持100%不动。

---

## 二、P0 三条链

先只跑通这三条，不要贪多：

| chain_id | 名称 | 说明 |
|----------|------|------|
| `ai_compute` | AI 算力链 | 已存在于产业链助手，有数据基础 |
| `semiconductor` | 半导体链 | 已存在于产业链助手，有数据基础 |
| `nev` | 新能源汽车链 | 已存在于产业链助手，有数据基础 |

---

## 三、任务清单（按顺序执行）

### 任务 1：在 industry_chain_evidence.duckdb 中建三张表

数据库路径：`outputs/industry_chain/industry_chain_evidence.duckdb`

三张表：

#### 3.1 `chain_dynamics` — 产业链动态总表

```sql
CREATE TABLE IF NOT EXISTS chain_dynamics (
    chain_id VARCHAR PRIMARY KEY,
    state_date DATE,
    prosperity_score DOUBLE,      -- 景气度评分 0-100
    regime VARCHAR,               -- 'expansion', 'contraction', 'recovery', 'overheat'
    event_count INTEGER,          -- 当日事件数
    lead_node VARCHAR,            -- 领涨节点
    lag_node VARCHAR,             -- 滞涨节点
    updated_at TIMESTAMP
);
```

#### 3.2 `industry_position` — 产业链环节仓位/资金位置

```sql
CREATE TABLE IF NOT EXISTS industry_position (
    id BIGINT PRIMARY KEY,
    chain_id VARCHAR,
    node_id VARCHAR,              -- 环节ID，如 'upstream', 'midstream', 'downstream'
    node_name VARCHAR,            -- 环节名称
    state_date DATE,
    fund_flow_score DOUBLE,       -- 资金流评分
    position_score DOUBLE,        -- 仓位评分
    momentum_score DOUBLE,        -- 动量评分
    state_hex VARCHAR,            -- Hermass state_hex（从 state_cube.duckdb 关联）
    updated_at TIMESTAMP
);
```

#### 3.3 `chain_event_cross` — 跨链/跨节点事件

```sql
CREATE TABLE IF NOT EXISTS chain_event_cross (
    id BIGINT PRIMARY KEY,
    chain_id VARCHAR,
    event_type VARCHAR,           -- 'policy', 'earnings', 'price_move', 'fund_flow'
    event_source VARCHAR,         -- 事件来源节点
    event_target VARCHAR,         -- 事件影响节点（可跨链）
    state_date DATE,
    impact_score DOUBLE,          -- 影响强度
    description TEXT,
    updated_at TIMESTAMP
);
```

**要求：**
- 使用 `duckdb` Python 接口建表
- 表已存在时跳过（`IF NOT EXISTS`）
- 为 `chain_id`, `state_date`, `node_id` 建索引

---

### 任务 2：写三个数据构建脚本

脚本位置：`scripts/`

#### 2.1 `scripts/build_chain_dynamics.py`

输入：
- `outputs/industry_chain/industry_chain_evidence.duckdb`
- `outputs/state_cube/state_cube.duckdb`（读取各行业 ETF/代表股的 state）
- `outputs/market_assets/market_assets.duckdb`（读取行业资金流）

输出：向 `chain_dynamics` 表写入数据

逻辑（MVP 版）：
1. 读取 P0 三条链的代表品种（从已有产业链助手的配置中提取）
2. 计算每条链的景气度评分（综合资金流入、价格动量、state 状态）
3. 判断 regime（基于景气度评分分段）
4. 统计当日事件数
5. 识别 lead_node / lag_node（哪个环节资金流最强/最弱）
6. 写入数据库

**注意：不要重新计算指标，从 state_cube.duckdb 和 market_assets.duckdb 读取已有数据。**

#### 2.2 `scripts/build_industry_position.py`

输入同上

输出：向 `industry_position` 表写入数据

逻辑（MVP 版）：
1. 对每条链的上中下游节点
2. 读取对应品种的资金流评分（从 market_assets）
3. 读取对应品种的 state_hex（从 state_cube）
4. 计算 position_score（基于收盘位置与布林带/均线的关系）
5. 计算 momentum_score（基于短期收益率）
6. 写入数据库

#### 2.3 `scripts/build_chain_event_cross.py`

输入：
- `outputs/industry_chain/industry_chain_evidence.duckdb`（已有的 chain_event 表）
- `scripts/build_macro_chain_prior.py` 的产出（宏观事件）

输出：向 `chain_event_cross` 表写入数据

逻辑（MVP 版）：
1. 读取已有事件数据
2. 识别跨链影响（如 AI 算力政策同时影响半导体）
3. 给每个事件打 impact_score
4. 写入数据库

---

### 任务 3：新增 /chain-studio 路由和最小模板

#### 3.1 路由（`web/main.py`）

新增路由：

```python
@app.get("/chain-studio", response_class=HTMLResponse)
async def chain_studio(request: Request):
    # 读取 chain_dynamics 最新数据
    # 只读 P0 三条链
    # 渲染模板
    return templates.TemplateResponse("chain-studio.html", {
        "request": request,
        "chains": chains_data,
        "page_title": "产业链工作台（新）"
    })
```

**约束：**
- 禁止修改 `/chain-assistant` 的路由
- 新路由使用独立 namespace
- 错误处理要有 fallback（数据库不存在时返回空表 + 提示）

#### 3.2 模板（`web/templates/chain-studio.html`）

最小页面结构：

```html
<!DOCTYPE html>
<html>
<head><title>产业链工作台（新）</title></head>
<body>
  <h1>产业链工作台（新）</h1>
  
  <!-- 热力总览表 -->
  <table>
    <thead>
      <tr>
        <th>产业链</th>
        <th>景气度</th>
        <th>状态</th>
        <th>事件数</th>
        <th>领涨环节</th>
      </tr>
    </thead>
    <tbody>
      {% for chain in chains %}
      <tr>
        <td>{{ chain.chain_id }}</td>
        <td>{{ chain.prosperity_score }}</td>
        <td>{{ chain.regime }}</td>
        <td>{{ chain.event_count }}</td>
        <td>{{ chain.lead_node }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  
  <p>旧版入口：<a href="/chain-assistant">产业链助手（旧）</a></p>
</body>
</html>
```

**要求：**
- 只展示热力总览，**不要**做节点图谱、RRG、时间线（那些是 Phase 2）
- 页面底部必须保留旧版入口链接
- 样式可以用 Tailwind（参考现有页面），但不做复杂动效

---

### 任务 4：更新导航

在 `web/templates/` 的导航栏（通常是 `base.html` 或各页面共用的导航片段）中：

- 保留原有的 `产业链助手（旧）` 入口，链接到 `/chain-assistant`
- 新增 `产业链工作台（新）` 入口，链接到 `/chain-studio`
- 两个入口同时显示

---

### 任务 5：验证 /chain-assistant 未被修改

执行以下检查，确保旧栏目完全未动：

```bash
git diff HEAD -- web/main.py | grep -A5 -B5 "chain-assistant" || echo "旧路由未修改"
git diff HEAD -- web/templates/chain-assistant.html || echo "旧模板未修改"
git diff HEAD -- scripts/build_chain_fund_manager_assistant.py || echo "旧脚本未修改"
```

如果有任何修改，必须回滚。

---

## 四、验收标准

| # | 验收项 | 通过标准 |
|---|--------|---------|
| 1 | 三张表已建 | `duckdb` 能 `.tables` 看到三张表 |
| 2 | 有真实数据 | P0 三条链在 `chain_dynamics` 中各至少有 1 行 |
| 3 | /chain-studio 可打开 | 本地 `curl http://localhost:8020/chain-studio` 返回 HTTP 200 |
| 4 | 页面展示正确 | 能看到 `chain_id`, `prosperity_score`, `regime`, `event_count`, `lead_node` |
| 5 | /chain-assistant 仍可访问 | 旧页面返回 HTTP 200，数据正常 |
| 6 | 旧栏目未被修改 | `git diff` 显示旧文件无变更 |
| 7 | 导航有两个入口 | 页面上同时看到"产业链助手（旧）"和"产业链工作台（新）" |

---

## 五、技术约束（来自 AGENTS.md）

1. **禁止在 `web/main.py` 里直接调用 `Agently.create_agent()`** — 产业链如需 AI 判断，Phase 3 会单独给你接口
2. **新增脚本只能放 `scripts/`**，由 `config/hermes_cron.json` 调用 — Phase 1 暂时手动跑，Phase 2 再纳入 cron
3. **记忆层统一用 `AgentMemory.duckdb`** — 产业链判断后续写入此处，但 Phase 1 不涉及
4. **复用 `state_cube.duckdb` 和 `market_assets.duckdb`** — 禁止重新计算指标状态

---

## 六、交付物

完成后请提供：

1. 变更文件清单（`git diff --name-only`）
2. 本地验证截图或 curl 输出（/chain-studio 和 /chain-assistant 各一次）
3. `chain_dynamics` 表前 5 行数据（`SELECT * FROM chain_dynamics LIMIT 5`）
4. 确认 `/chain-assistant` 未被修改的证据

---

## 七、禁止事项

| 禁止项 | 说明 |
|--------|------|
| ❌ 修改 `/chain-assistant` 任何文件 | 旧栏目100%保留 |
| ❌ 删除旧导航入口 | 双轨并行必须同时可见 |
| ❌ 做 Phase 2 的内容 | 不要写节点图谱、RRG、事件时间线、候选池观察台 |
| ❌ 重新计算指标 | 从 state_cube / market_assets 读取 |
| ❌ 新增第 4 条链 | P0 只跑 ai_compute / semiconductor / nev |
| ❌ 写死双轨并行期限 | 2-4 周是观察期，代码里不要硬编码过期时间 |

---

**请开始执行。完成后按第六节交付物回复。**
