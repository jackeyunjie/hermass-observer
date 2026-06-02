# 调试任务：研究预览页"生成研究卡"按钮点击无响应

## 项目背景
Hermass Observer 是一个 Python FastAPI + Jinja2 的股票研究系统。
- 后端：`web/main.py` (FastAPI)
- 前端模板：`web/templates/index.html` (Jinja2 + TailwindCSS)
- 研究模块：`hermass_platform/research/`

## 问题描述
用户在首页的研究预览面板输入股票代码（如 601318），点击"生成研究卡"按钮后，页面没有响应。

## 技术栈
- FastAPI (后端)
- Jinja2 模板引擎
- 普通 HTML form 表单提交（非 AJAX/fetch）

## 关键文件位置

### 1. 前端表单 (`web/templates/index.html`, 第 175-196 行)
```html
<section class="panel" id="research-preview">
  <div class="panel-head">
    <h2>研究预览</h2>
    <span>快速卡 / 深度卡 / 证据卡</span>
  </div>
  <form method="post" class="form">
    <input type="hidden" name="mode" value="{{ mode }}" />
    <label>
      股票代码
      <input name="stock_code" value="{{ stock_code }}" />
    </label>
    <label>
      展开深度
      <select name="render_profile">
        <option value="standard">标准</option>
        <option value="full">完整</option>
      </select>
    </label>
    <button type="submit">生成研究卡</button>
  </form>
</section>
```

### 2. 后端路由 (`web/main.py`, 第 2388-2417 行)
```python
@app.post("/", response_class=HTMLResponse)
def preview_cards(
    request: Request,
    stock_code: str = Form("000021.SZ"),
    render_profile: str = Form("full"),
    mode: str = Form("direction"),
) -> HTMLResponse:
    profile = get_current_profile(request)
    cards = _render_cards(stock_code, render_profile)
    return templates.TemplateResponse(
        request, "index.html", {
            "cards": cards,
            "stock_code": stock_code,
            "render_profile": render_profile,
            ...
        }
    )
```

### 3. 卡片渲染函数 (`web/main.py`, 第 2321-2349 行)
```python
def _render_cards(stock_code: str, render_profile: str) -> dict[str, Any]:
    foundation_db = find_foundation_db()
    if not foundation_db:
        return {"error": "未找到 foundation DB。"}
    as_of_date = _latest_research_as_of_date()
    try:
        evidence = build_external_research_evidence(
            stock_code=stock_code.strip().upper(),
            as_of_date=as_of_date,
            foundation_db=foundation_db,
        )
        return {
            "quick": format_quick_research_card(evidence),
            "deep": format_deep_research_card(evidence, render_profile=render_profile),
            "evidence": format_evidence_card(evidence),
            ...
        }
    except Exception as exc:
        return {"error": f"研究卡构建失败：{exc}", ...}
```

## 需要你做的事

### 第一步：诊断
请帮我排查以下可能原因：
1. 检查 `find_foundation_db()` 是否能找到 Foundation DB 文件（搜索 `outputs/` 或 `fixtures/` 下的 `.duckdb` 文件）
2. 检查 `_latest_research_as_of_date()` 是否能返回有效日期
3. 检查 `build_external_research_evidence()` 是否会抛出异常（查看 `hermass_platform/research/external_research_evidence.py`）
4. 检查 CSS 样式是否导致按钮视觉上看起来可以点击但实际上不可交互（检查 `web/static/style.css` 中 `.form` 和 `button` 的样式）

### 第二步：修复
根据诊断结果，修复问题。可能的修复包括：
- 如果 Foundation DB 找不到：添加正确的 DB 路径或修复 `find_foundation_db()` 函数
- 如果 `build_external_research_evidence` 有 bug：修复该函数中的问题
- 如果前端表单有提交问题：确保 form 的 action 或 submit 行为正确
- 如果 CSS 阻止了交互：修复相关样式

### 第三步：验证
修复后请确认：
- 在浏览器中打开 `http://localhost:8000`
- 在"研究预览"面板输入股票代码如 601318
- 点击"生成研究卡"按钮
- 页面应该展示 快速卡 / 深度卡 / 证据卡 三张卡片

## 额外信息
- 项目有一个 Makefile，可以用 `make run` 或 `make dev` 启动
- 虚拟环境在 `.venv/` 目录下
- 数据库文件在 `outputs/foundation_db/` 或 `fixtures/` 下
- 日志在 `logs/` 目录下

请从诊断开始，然后给出修复方案，最后执行修复。
