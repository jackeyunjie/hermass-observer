# 文案修正补丁

版本：v1.0
日期：2026-05-23
适用文件：`scripts/daily_research_brief.py`
修改范围：展示文案（Markdown + HTML），不动计算逻辑

---

## 修改 1：Markdown 聚焦表列名（State环境 → 三周期状态，本地验证/匹配 → 验证结论）

**位置**：`focus_markdown_table()` 函数，行 554

**修改前**：
```python
        "| 股票 | 行业 | 策略 | 生命周期 | 适配理由 | State环境 | 本地验证/匹配 |",
```

**修改后**：
```python
        "| 股票 | 行业 | 策略 | 趋势阶段 | 适配理由 | 三周期状态 | 验证结论 |",
```

---

## 修改 2：HTML 聚焦表列名（State环境 → 三周期状态，本地验证/匹配 → 验证结论）

**位置**：`build_html()` 函数，行 1019-1020

**修改前**：
```html
            <th>State环境</th>
            <th>本地验证/匹配</th>
```

**修改后**：
```html
            <th>三周期状态</th>
            <th>验证结论</th>
```

---

## 修改 3：HTML metric card "全三 E/F 池" 增加人话注释

**位置**：`build_html()` 函数，行 971

**修改前**：
```html
      <div class="metric">全三 E/F 池<b>{esc(summary["all_three_ef_count"])}</b><span>{esc(delta_text)}</span></div>
```

**修改后**：
```html
      <div class="metric">全三强势池<b>{esc(summary["all_three_ef_count"])}</b><span>月/周/日线同时处于强势状态 | {esc(delta_text)}</span></div>
```

---

## 修改 4：HTML metric card 校准状态提示优化

**位置**：`build_html()` 函数，行 976

**修改前**：
```html
      <div class="metric">校准状态<b>{esc(cal["status"])}</b><span>{esc("历史验证数据积累中" if (cal["reason"] or "") == "calibration_not_available" else (cal["reason"] or ""))}</span></div>
```

**修改后**：
```html
      <div class="metric">校准状态<b>{esc(cal["status"])}</b><span>{esc(cal_reason_text)}</span></div>
```

**说明**：`cal_reason_text` 变量已在行 694 定义，直接使用即可。

---

## 修改 5：HTML 市场阶段卡片文案优化（加成 → 环境系数，释放密度 → 突破密度）

**位置**：`build_html()` 函数，行 888-910

**修改前**：
```python
        factor_text = f"加成 {factor:.2f}" if factor is not None else ""
        factors_line = " / ".join(f"{esc(k)} {v:.2f}" for k, v in factors.items()) if factors else ""
        indicator_items = []
        if indicators.get("pool_size") is not None:
            indicator_items.append(f"全三 E/F 池 {indicators['pool_size']} 只")
        if indicators.get("pool_change_rate_5d") is not None:
            indicator_items.append(f"5日变化 {indicators['pool_change_rate_5d']:+.1%}")
        if indicators.get("contraction_release_density") is not None:
            indicator_items.append(f"释放密度 {indicators['contraction_release_density']:.2%}")
        indicator_text = " | ".join(indicator_items) if indicator_items else ""
        phase_html = f"""
    <div class="phase-card">
      <div class="phase-header">
        <span class="phase-badge">{label}</span>
        <span class="phase-confidence">{esc(confidence_text)}</span>
      </div>
      <p class="phase-desc">{description}</p>
      <p class="phase-hint">策略提示：{hint}</p>
      <p class="phase-best">最佳适配策略：<strong>{best_strategy}</strong> <span>{esc(factor_text)}</span></p>
      <p class="phase-factors">各策略加成：{factors_line}</p>
      {f'<p class="phase-indicators">核心指标：{esc(indicator_text)}</p>' if indicator_text else ''}
    </div>
"""
```

**修改后**：
```python
        factor_text = f"环境系数 {factor:.2f}（>1 表示环境有利）" if factor is not None else ""
        factors_line = " / ".join(f"{esc(k)} {v:.2f}" for k, v in factors.items()) if factors else ""
        indicator_items = []
        if indicators.get("pool_size") is not None:
            indicator_items.append(f"强势池 {indicators['pool_size']} 只")
        if indicators.get("pool_change_rate_5d") is not None:
            indicator_items.append(f"5日扩张 {indicators['pool_change_rate_5d']:+.1%}")
        if indicators.get("contraction_release_density") is not None:
            indicator_items.append(f"突破密度 {indicators['contraction_release_density']:.2%}（从收缩中突破的股票占比）")
        indicator_text = " | ".join(indicator_items) if indicator_items else ""
        phase_html = f"""
    <div class="phase-card">
      <div class="phase-header">
        <span class="phase-badge">{label}</span>
        <span class="phase-confidence">{esc(confidence_text)}</span>
      </div>
      <p class="phase-desc">{description}</p>
      <p class="phase-hint">策略提示：{hint}</p>
      <p class="phase-best">当前最适策略：<strong>{best_strategy}</strong> <span>{esc(factor_text)}</span></p>
      <p class="phase-factors">各策略环境系数：{factors_line}</p>
      {f'<p class="phase-indicators">核心指标：{esc(indicator_text)}</p>' if indicator_text else ''}
    </div>
"""
```

---

## 附录：已完成的文案修改（无需再次应用）

以下修改已在 `daily_research_brief.py` 的最新版本中完成，本补丁不再重复：

| 位置 | 修改内容 | 状态 |
|------|---------|------|
| Markdown 概览 | "提醒信号" → "今日触发信号" | 已完成 |
| Markdown 概览 | "展示信号" → "环境匹配信号" | 已完成 |
| Markdown 概览 | "VCP路径命中" → "VCP 收缩释放" | 已完成 |
| Markdown 概览 | "布林波动稳定" → "布林波动平稳" | 已完成 |
| Markdown 概览 | "2560 full_match" → "2560 全匹配" | 已完成 |
| Markdown 概览 | "宏观先验" → "宏观环境评分" | 已完成 |
| Markdown 概览 | "风格先验" → "市场风格" | 已完成 |
| Markdown 章节标题 | "最佳适配信号聚焦表" → "最佳适配聚焦" | 已完成 |
| Markdown 章节标题 | "2560 State / 市场匹配分组" → "2560 策略：市场匹配分组" | 已完成 |
| Markdown 章节标题 | "最佳适配与适配信号" → "全部匹配信号" | 已完成 |
| Markdown 章节标题 | "iFinD 场景聚焦" → "基本面聚焦" | 已完成 |
| Markdown 章节标题 | "说明" → "阅读提示" | 已完成 |
| HTML metric card | "提醒信号" → "今日触发信号" | 已完成 |
| HTML metric card | "展示信号" → "环境匹配信号" | 已完成 |
| HTML metric card | "VCP路径命中" → "VCP 收缩释放" | 已完成 |
| HTML metric card | "布林波动稳定" → "布林波动平稳" | 已完成 |
| HTML metric card | "2560 full_match" → "2560 全匹配" | 已完成 |
| HTML metric card | "布林波动×生命周期" → "布林强盗：波动 × 阶段分布" | 已完成 |
| HTML metric card | "宏观先验" → "宏观环境评分" | 已完成 |
| HTML 明细表列名 | "iFinD场景" → "基本面摘要" | 已完成 |
| HTML 明细表列名 | "State" → "三周期状态" | 已完成 |
| HTML 明细表列名 | "SR" → "价格位置" | 已完成 |
| HTML 明细表列名 | "统计" → "验证结论" | 已完成 |
| 底部说明 | "不输出具体操作指令" → "不输出买入、卖出等具体操作建议" | 已完成 |
| 底部说明 | "iFinD 场景聚焦" → "基本面聚焦" | 已完成 |

---

## 实施步骤

1. 打开 `scripts/daily_research_brief.py`
2. 按上述 5 个修改项逐一替换
3. 运行 `python3 -m py_compile scripts/daily_research_brief.py` 验证语法
4. 运行 `python3 scripts/daily_research_brief.py --date 2026-05-22` 生成报告，检查文案效果

---

## 免责声明

本补丁仅修改展示文案，不改变任何计算逻辑、数据流或策略规则。所有修改均符合合规要求，不增加投资建议，不承诺收益。
