#!/usr/bin/env python3
"""
Generate Daily Trading SOP (Standard Operating Procedure).

Aggregates market phase, macro prior, strategy reminders, and unified view data
into a single trading-ready checklist with:
- Pre-market environment confirmation
- Candidate trade list (sorted by 适配度 + 大周期背景)
- Execution parameters for top 5 candidates
- Risk warnings

Usage:
    python3 scripts/generate_daily_trading_sop.py --date 2026-05-22
    python3 scripts/generate_daily_trading_sop.py --date 2026-05-22 --capital 2000000

Outputs:
    outputs/trading_sop/daily_trading_sop_YYYYMMDD.md
    outputs/trading_sop/daily_trading_sop_YYYYMMDD.json
    public/daily_trading_sop_YYYYMMDD.html
"""

import argparse
import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

import duckdb
import pandas as pd
import numpy as np

# Include project root and scripts directory
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_project_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_project_root / "scripts"))

from position_sizing import calculate_dynamic_position, compute_macro_coeff_from_mn1, compute_industry_coeff_from_mn1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_sop")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PUBLIC_DIR = PROJECT_ROOT / "public"
TRADING_SOP_DIR = OUTPUTS_DIR / "trading_sop"

# Research-Only 合规声明
RESEARCH_ONLY_DISCLAIMER = (
    "Research-Only 声明：本清单为系统环境识别结果，仅供内部研究参考，不构成任何形式的投资建议。"
    "具体交易决策（含入场时机、头寸规模、止损设置）请基于自身风险承受能力独立判断。"
)


def _fmt_date(date: str) -> str:
    return date.replace("-", "")


def safe_load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        logger.warning("Missing file: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("JSON parse error in %s: %s", path, e)
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Data loaders
# ═════════════════════════════════════════════════════════════════════════════

def load_market_phase(date: str) -> dict:
    path = OUTPUTS_DIR / "market_phase" / f"market_phase_{_fmt_date(date)}.json"
    data = safe_load_json(path)
    return data or {}


def load_macro_prior(date: str) -> dict:
    path = OUTPUTS_DIR / "macro_chain_prior" / f"macro_chain_prior_{_fmt_date(date)}.json"
    data = safe_load_json(path)
    return data or {}


def load_reminders(date: str) -> list[dict]:
    path = OUTPUTS_DIR / "strategy_reminders" / f"reminder_{_fmt_date(date)}.json"
    data = safe_load_json(path)
    if data is None:
        return []
    return data.get("reminders", [])


def load_unified_view(date: str) -> pd.DataFrame:
    db_path = OUTPUTS_DIR / "unified_view" / "unified_daily_snapshot.duckdb"
    if not db_path.exists():
        logger.warning("Unified view DB not found: %s", db_path)
        return pd.DataFrame()
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        df = con.execute(
            "SELECT * FROM unified_daily_snapshot WHERE snapshot_date = ?",
            [date],
        ).fetchdf()
        con.close()
    except Exception as e:
        logger.warning("Failed to query unified view: %s", e)
        return pd.DataFrame()
    return df


def load_close_prices_from_foundation(date: str, stock_codes: list[str]) -> dict[str, float]:
    """Load latest close prices from foundation DB for stocks not in unified view."""
    # Find the foundation DB for the given date
    foundation_db = OUTPUTS_DIR / f"p116_foundation_{_fmt_date(date)}" / "p116_foundation.duckdb"
    if not foundation_db.exists():
        # Try previous date
        from datetime import datetime, timedelta
        dt = datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)
        prev_date = dt.strftime("%Y-%m-%d")
        foundation_db = OUTPUTS_DIR / f"p116_foundation_{_fmt_date(prev_date)}" / "p116_foundation.duckdb"
    if not foundation_db.exists():
        logger.warning("Foundation DB not found for %s", date)
        return {}

    try:
        con = duckdb.connect(str(foundation_db), read_only=True)
        placeholders = ",".join(["?"] * len(stock_codes))
        query = f"""
            SELECT stock_code, close
            FROM daily_bars
            WHERE stock_code IN ({placeholders})
              AND date = (SELECT MAX(date) FROM daily_bars)
        """
        df = con.execute(query, stock_codes).fetchdf()
        con.close()
        return {row["stock_code"]: float(row["close"]) for _, row in df.iterrows()}
    except Exception as e:
        logger.warning("Failed to query foundation DB: %s", e)
        return {}


def load_market_asset_state(date: str) -> dict:
    """加载 market_assets_state DuckDB，返回 HS300 月线 + 行业 ETF 月线映射。"""
    db_path = OUTPUTS_DIR / f"market_assets_state_expanded_v2_{_fmt_date(date)}" / "market_assets_state.duckdb"
    if not db_path.exists():
        db_path = OUTPUTS_DIR / f"market_assets_state_{_fmt_date(date)}" / "market_assets_state.duckdb"
    if not db_path.exists():
        # Fallback: latest matching dir
        candidates = sorted(OUTPUTS_DIR.glob("market_assets_state_*/market_assets_state.duckdb"))
        if candidates:
            db_path = candidates[-1]
        else:
            return {"hs300_mn1_score": None, "industry_mn1_map": {}}

    try:
        con = duckdb.connect(str(db_path), read_only=True)
        rows = con.execute("""
            SELECT symbol, name, asset_type, sw_l1,
                   mn1_state_hex, mn1_state_score
            FROM latest_market_asset_state
        """).fetchall()
        con.close()
    except Exception as e:
        logger.warning("Failed to read market_assets_state: %s", e)
        return {"hs300_mn1_score": None, "industry_mn1_map": {}}

    result: dict = {"hs300_mn1_score": None, "industry_mn1_map": {}}
    for symbol, name, atype, sw_l1, hex_, score in rows:
        if symbol == "000300.SH":
            result["hs300_mn1_score"] = int(score) if score is not None else None
            result["hs300_mn1_hex"] = hex_ or ""
        if atype == "industry_etf" and sw_l1:
            result["industry_mn1_map"][str(sw_l1).strip()] = {
                "symbol": symbol,
                "name": name,
                "mn1_hex": hex_ or "",
                "mn1_score": int(score) if score is not None else None,
            }
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Eligibility & scoring
# ═════════════════════════════════════════════════════════════════════════════

def is_eligible(rem: dict) -> bool:
    """Determine if a reminder should be included in the SOP candidate list."""
    strategy = rem.get("strategy", {})
    fit = rem.get("strategy_environment_fit", "")

    # Include if any of:
    # 1. strategy_environment_fit in (最佳适配, 适配)
    # 2. signal_type is entry
    # NOTE: RR filtering removed — 阻力位止盈违背"让利润奔跑"原则
    if fit in ("最佳适配", "适配"):
        return True
    if strategy.get("signal_type") == "entry":
        return True
    return False


def score_reminder(rem: dict) -> float:
    """Higher score = higher priority in candidate list.
    
    NOTE: RR sorting removed. Now sorted by: 适配度 + 大周期背景.
    """
    w1_mn1 = rem.get("w1_mn1_env", {})
    fit = rem.get("strategy_environment_fit", "")
    score = 0.0

    # 大周期共振 boost
    if w1_mn1.get("label") == "大周期共振":
        score += 200

    # 适配度 boost
    fit_scores = {"最佳适配": 100, "适配": 50, "弱适配": 20, "不适配": 0}
    score += fit_scores.get(fit, 0)

    return score


# ═════════════════════════════════════════════════════════════════════════════
# Stop price & position sizing
# ═════════════════════════════════════════════════════════════════════════════

def compute_stop_price(rem: dict, d1_close: float) -> float:
    """Compute a conservative stop price for a reminder.
    
    NOTE: nearest_support removed as primary stop. Strategy default rules only.
    阻力位不再作为止损依据，改用策略原生出场规则。
    """
    strategy_id = rem.get("strategy", {}).get("strategy_id", "")

    # Strategy default stops only
    if strategy_id == "vcp":
        # Hard stop -6%
        return d1_close * 0.94
    elif strategy_id == "ma2560":
        # Use a moderate stop (~5%)
        return d1_close * 0.95
    elif strategy_id == "bollinger_bandit":
        # Tighter stop (~4%)
        return d1_close * 0.96
    else:
        return d1_close * 0.95


def compute_position_size(entry: float, stop: float, capital: float, max_risk_pct: float = 0.02) -> dict:
    """Compute position sizing parameters."""
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0 or entry <= 0:
        return {"shares": 0, "investment": 0, "risk_amount": 0, "risk_pct_of_capital": 0}

    max_risk_amount = capital * max_risk_pct
    shares = int(max_risk_amount / risk_per_share)
    # Round to nearest 100 (A-share lot size)
    shares = (shares // 100) * 100
    if shares < 100:
        shares = 0

    investment = shares * entry
    risk_amount = shares * risk_per_share
    risk_pct = risk_amount / capital if capital > 0 else 0

    return {
        "shares": shares,
        "investment": round(investment, 2),
        "risk_amount": round(risk_amount, 2),
        "risk_pct_of_capital": round(risk_pct * 100, 2),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Environment analysis
# ═════════════════════════════════════════════════════════════════════════════

def analyze_market_env(market_phase: dict, macro_prior: dict) -> dict:
    """Produce pre-market environment summary."""
    phase = market_phase.get("market_phase", "unknown")
    phase_label = market_phase.get("phase_label", "未知")
    confidence = market_phase.get("confidence", 0)
    implications = market_phase.get("strategy_implications", {})

    macro = macro_prior.get("macro_prior", {})
    macro_score = macro.get("score_0_10", 5.0)
    macro_conf = macro.get("confidence", 0)

    # Position sizing recommendation
    phase_to_position = {
        "emergence": ("正常", "标准仓位"),
        "trending": ("积极", "可适当加仓"),
        "extension": ("谨慎", "降低仓位或只开高确信度信号"),
        "contraction": ("防御", "空仓或极小仓位"),
        "release": ("防御", "等待释放完成"),
    }
    position_rec = phase_to_position.get(phase, ("观望", "等待明确信号"))

    # Best fit strategy
    best_strategy = ""
    best_factor = 0.0
    for sid, info in implications.items():
        factor = info.get("factor", 0)
        if factor > best_factor:
            best_factor = factor
            best_strategy = sid

    # One-sentence summary
    summary_parts = [
        f"市场阶段：{phase_label}（置信度 {confidence:.0%}）",
    ]
    if best_strategy:
        summary_parts.append(f"最佳适配策略：{best_strategy}（加成系数 {best_factor:.2f}）")
    summary_parts.append(f"宏观先验：{macro_score:.1f}/10（置信度 {macro_conf:.0%}）")
    summary_parts.append(f"建议仓位：{position_rec[0]} — {position_rec[1]}")

    return {
        "phase": phase,
        "phase_label": phase_label,
        "confidence": confidence,
        "best_strategy": best_strategy,
        "best_factor": best_factor,
        "macro_score": macro_score,
        "macro_confidence": macro_conf,
        "position_recommendation": position_rec[0],
        "position_detail": position_rec[1],
        "one_sentence": "；".join(summary_parts),
        "strategy_implications": implications,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Risk warnings
# ═════════════════════════════════════════════════════════════════════════════

def generate_risk_warnings(candidates: list[dict]) -> list[str]:
    warnings = []
    if not candidates:
        warnings.append("⚠️ 今日无符合条件的候选信号，建议空仓观望。")
        return warnings

    total = len(candidates)
    double_contraction = sum(1 for c in candidates if c.get("w1_mn1_label") == "双重收缩")
    resonance = sum(1 for c in candidates if c.get("w1_mn1_label") == "大周期共振")

    if total > 0 and double_contraction / total > 0.5:
        warnings.append(
            f"⚠️ 大周期支撑偏弱：{double_contraction}/{total} 只候选股的大周期背景为「双重收缩」，"
            f"建议降低仓位或仅选取大周期共振的标的。"
        )

    if resonance < 3:
        warnings.append(
            f"⚠️ 大周期共振标的稀缺：仅 {resonance}/{total} 只候选股处于大周期共振环境，"
            f"趋势持续性可能偏弱。"
        )

    # Strategy concentration
    strategy_counts = {}
    for c in candidates:
        sid = c.get("strategy_id", "unknown")
        strategy_counts[sid] = strategy_counts.get(sid, 0) + 1
    dominant = max(strategy_counts, key=strategy_counts.get) if strategy_counts else ""
    dominant_pct = strategy_counts.get(dominant, 0) / total if total > 0 else 0
    if dominant_pct > 0.7:
        warnings.append(
            f"⚠️ 策略集中度偏高：{dominant} 占比 {dominant_pct:.0%}，"
            f"建议分散策略暴露以降低相关性风险。"
        )

    if not warnings:
        warnings.append("✅ 风险指标正常，可按计划执行。")

    return warnings


# ═════════════════════════════════════════════════════════════════════════════
# Output generators
# ═════════════════════════════════════════════════════════════════════════════

def generate_md(sop_data: dict, date: str) -> str:
    env = sop_data["environment"]
    candidates = sop_data["candidates"]
    top5 = sop_data["top5_execution_params"]
    warnings = sop_data["risk_warnings"]
    capital = sop_data["capital"]

    lines = [
        f"> {RESEARCH_ONLY_DISCLAIMER}",
        "",
        f"# 每日交易准备清单 — {date}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 总资金：¥{capital:,.0f}",
        f"> 仓位模型：{env.get('dynamic_reason', '标准')}",
        f"> 数据来源：market_phase / macro_chain_prior / strategy_reminders / unified_daily_snapshot",
        "",
        "---",
        "",
        "## 一、盘前环境确认",
        "",
        f"**{env['one_sentence']}**",
        "",
        "| 维度 | 数值 |",
        "|---|---|",
        f"| 市场阶段 | {env['phase_label']} ({env['phase']}) |",
        f"| 阶段置信度 | {env['confidence']:.0%} |",
        f"| 最佳适配策略 | {env['best_strategy']} (加成 {env['best_factor']:.2f}) |",
        f"| 宏观先验评分 | {env['macro_score']:.1f}/10 (置信度 {env['macro_confidence']:.0%}) |",
        f"| 建议仓位 | **{env['position_recommendation']}** — {env['position_detail']} |",
        f"| 大盘月线 | 沪深300 MN1={env.get('hs300_mn1_hex', '?')} → 系数 **{env.get('macro_mn1_coeff', 1.0):.2f}** |",
        f"| 动态总仓位 | **{env.get('dynamic_allocation', 0.5):.0%}**（基础 50% × 阶段 × 策略加成 × 大盘月线） |",
        f"| 动态单笔风险 | **{env.get('dynamic_per_trade_risk', 2.0):.1f}%**（{env.get('dynamic_reason', '')}） |",
        f"| 建议最大持仓 | {env.get('dynamic_max_positions', 4)} 只 |",
        "",
        "### 策略加成明细",
        "",
        "| 策略 | 适配度 | 加成系数 |",
        "|---|---|---|",
    ]
    for sid, info in env.get("strategy_implications", {}).items():
        lines.append(f"| {sid} | {info.get('fit', '-')} | {info.get('factor', '-')} |")

    lines.extend([
        "",
        "---",
        "",
        "## 二、候选交易清单",
        "",
        f"> 共筛选出 **{len(candidates)}** 只符合条件的候选股（原始信号 {sop_data['total_signals']} 只）",
        "",
        "| 排序 | 代码 | 名称 | 策略 | RR | 大周期背景 | 适配度 | 生命周期 | 风险提示 |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    for i, c in enumerate(candidates, 1):
        bg = c.get("w1_mn1_label", "-")
        lifecycle = c.get("lifecycle_stage", "-")
        fit = c.get("strategy_fit", "-")
        risk_note = c.get("risk_note", "-") or "-"
        if str(risk_note).lower() in ("nan", "none", "null"):
            risk_note = "-"
        lines.append(
            f"| {i} | {c['stock_code']} | {c['stock_name']} | {c['strategy_id']} | {bg} | {fit} | {lifecycle} | {risk_note} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、前 5 只执行参数",
        "",
        "> **注意**：入场价以次日开盘价为准，以下使用最新收盘价作为参考估算。止损价按策略默认规则计算。",
        "",
    ])

    for i, item in enumerate(top5, 1):
        p = item["params"]
        lines.extend([
            f"### {i}. {item['stock_code']} {item['stock_name']} — {item['strategy_id']}",
            "",
            "| 参数 | 数值 | 说明 |",
            "|---|---|---|",
            f"| 入场价（参考） | ¥{item['entry_price']:.2f} | 次日开盘价，以下为收盘价参考 |",
            f"| 止损价 | ¥{item['stop_price']:.2f} | {item['stop_method']} |",
            f"| 单笔风险 | ¥{p['risk_amount']:,.0f} ({p['risk_pct_of_capital']:.2f}%) | 动态风险预算 {item.get('dynamic_risk_pct', 2.0):.1f}% |",
            # NOTE: RR display removed — 阻力位止盈违背"让利润奔跑"原则
            f"| 仓位模型 | {item.get('dynamic_reason', '标准')} | 阶段 × 策略加成 × 适配度 |",
            f"| 大周期背景 | {item['w1_mn1_label']} | {item['w1_mn1_desc']} |",
            f"| 适配度 | {item['strategy_fit']} | {item['fit_reasons'][:60]}... |" if len(item.get('fit_reasons', '')) > 60 else f"| 适配度 | {item['strategy_fit']} | {item.get('fit_reasons', '-')} |",
            "",
            "**出场规则优先级：**",
            "",
        ])
        for rule in item["exit_rules"]:
            lines.append(f"1. {rule}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 四、风险预警",
        "",
    ])
    for w in warnings:
        lines.append(f"- {w}")

    lines.extend([
        "",
        "### 当日信号统计",
        "",
        f"- 总候选信号：{len(candidates)} 只",
        # NOTE: RR statistics removed — 阻力位止盈违背"让利润奔跑"原则
        f"- 大周期共振：{sum(1 for c in candidates if c.get('w1_mn1_label') == '大周期共振')} 只",
        f"- 双重收缩：{sum(1 for c in candidates if c.get('w1_mn1_label') == '双重收缩')} 只",
        f"- VCP 信号：{sum(1 for c in candidates if c.get('strategy_id') == 'vcp')} 只",
        f"- MA2560 信号：{sum(1 for c in candidates if c.get('strategy_id') == 'ma2560')} 只",
        f"- Bollinger 信号：{sum(1 for c in candidates if c.get('strategy_id') == 'bollinger_bandit')} 只",
        "",
        "---",
        "",
        "> ⚠️ **免责声明**：本清单由系统自动生成，仅供研究参考。所有交易决策需结合实时盘口、",
        "> 资金流向及个股公告综合判断。Past performance is not indicative of future results.",
        "",
    ])

    return "\n".join(lines)


def generate_html(sop_data: dict, date: str) -> str:
    md = generate_md(sop_data, date)
    # Simple markdown-to-html conversion
    html_lines = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN">',
        "<head>",
        '  <meta charset="UTF-8">',
        f"  <title>每日交易准备清单 — {date}</title>",
        "  <style>",
        "    .disclaimer { background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin-bottom: 20px; font-size: 14px; color: #92400e; }",
        "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #333; }",
        "    h1 { color: #1a1a1a; border-bottom: 2px solid #2563eb; padding-bottom: 10px; }",
        "    h2 { color: #1a1a1a; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; margin-top: 32px; }",
        "    h3 { color: #374151; margin-top: 24px; }",
        "    table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14px; }",
        "    th, td { border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }",
        "    th { background: #f3f4f6; font-weight: 600; }",
        "    tr:nth-child(even) { background: #f9fafb; }",
        "    .warning { color: #dc2626; font-weight: 500; }",
        "    .ok { color: #16a34a; font-weight: 500; }",
        "    code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 13px; }",
        "    blockquote { border-left: 4px solid #2563eb; margin: 0; padding-left: 16px; color: #4b5563; }",
        "  </style>",
        "</head>",
        "<body>",
        f'  <div class="disclaimer">{RESEARCH_ONLY_DISCLAIMER}</div>',
    ]

    # Very simple md-to-html
    in_table = False
    in_ul = False
    in_ol = False
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped.startswith("> "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<blockquote>{stripped[2:]}</blockquote>")
        elif stripped.startswith("| ") and "|" in stripped[2:]:
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            if not in_table:
                html_lines.append("<table>")
                in_table = True
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if "---" in stripped or all(set(c) <= set(" -") for c in cells):
                continue  # Skip md table separator
            tag = "th" if cells and cells[0].lower() in ("排序", "参数", "维度", "策略", "来源") else "td"
            html_lines.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        elif stripped == "":
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append("<p></p>")
        elif stripped.startswith("- "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            if not in_ul:
                html_lines.append("<ul>"); in_ul = True
            html_lines.append(f"<li>{stripped[2:]}</li>")
        elif stripped.startswith("1. "):
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if not in_ol:
                html_lines.append("<ol>"); in_ol = True
            html_lines.append(f"<li>{stripped[3:]}</li>")
        else:
            if in_table:
                html_lines.append("</table>"); in_table = False
            if in_ul:
                html_lines.append("</ul>"); in_ul = False
            if in_ol:
                html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<p>{stripped}</p>")

    if in_table:
        html_lines.append("</table>")
    if in_ul:
        html_lines.append("</ul>")
    if in_ol:
        html_lines.append("</ol>")

    html_lines.extend([
        "</body>",
        "</html>",
    ])
    return "\n".join(html_lines)


# ═════════════════════════════════════════════════════════════════════════════
# Main builder
# ═════════════════════════════════════════════════════════════════════════════

def build_sop(date: str, capital: float = 1_000_000) -> dict:
    logger.info("Building daily trading SOP for %s (capital=%.0f)", date, capital)

    # 1. Load data
    market_phase = load_market_phase(date)
    macro_prior = load_macro_prior(date)
    reminders = load_reminders(date)
    unified_df = load_unified_view(date)

    if not reminders:
        logger.error("No reminders found for %s", date)
        return {"error": "No reminders", "date": date}

    # Build unified lookup
    unified_lookup = {}
    if not unified_df.empty:
        for _, row in unified_df.iterrows():
            unified_lookup[row["stock_code"]] = row.to_dict()

    # Pre-load close prices from foundation for stocks not in unified view
    reminder_codes = [r.get("stock_code", "") for r in reminders if r.get("stock_code")]
    missing_codes = [c for c in reminder_codes if c not in unified_lookup]
    foundation_prices = load_close_prices_from_foundation(date, missing_codes)
    logger.info("Foundation fallback prices loaded for %d stocks", len(foundation_prices))

    # 1b. Load market asset state for macro/industry MN1 coefficients
    mas = load_market_asset_state(date)
    hs300_mn1_score = mas.get("hs300_mn1_score")
    industry_mn1_map = mas.get("industry_mn1_map", {})
    macro_mn1_coeff = compute_macro_coeff_from_mn1(hs300_mn1_score)
    logger.info("HS300 MN1 score=%s → macro_coeff=%.2f, %d industry ETFs",
                hs300_mn1_score, macro_mn1_coeff, len(industry_mn1_map))

    # 2. Environment analysis
    env = analyze_market_env(market_phase, macro_prior)

    # 2a. Dynamic position sizing from environment
    market_phase_key = env.get("phase", "undetermined")
    strategy_boost = env.get("best_factor", 1.0)
    macro_quadrant = "复苏"
    macro_raw = macro_prior.get("macro_prior", {})
    if macro_raw:
        macro_quadrant = macro_raw.get("quadrant") or macro_raw.get("regime") or "复苏"
    env_pos = calculate_dynamic_position(
        market_phase=market_phase_key,
        strategy_boost=strategy_boost,
        macro_quadrant=macro_quadrant,
        fit_level="最佳适配",
        macro_mn1_coeff=macro_mn1_coeff,
    )
    env["dynamic_allocation"] = env_pos["total_allocation_pct"]
    env["dynamic_per_trade_risk"] = env_pos["per_trade_risk_pct"]
    env["dynamic_max_positions"] = env_pos["max_positions"]
    env["dynamic_reason"] = env_pos["reason"]
    env["dynamic_allow_new"] = env_pos["allow_new_positions"]
    env["hs300_mn1_hex"] = mas.get("hs300_mn1_hex", "")
    env["hs300_mn1_score"] = hs300_mn1_score
    env["macro_mn1_coeff"] = macro_mn1_coeff
    logger.info("Market phase: %s (%s), position: %s", env["phase_label"], env["phase"], env["position_recommendation"])

    # 3. Filter & score candidates
    candidates_raw = []
    for rem in reminders:
        if not is_eligible(rem):
            continue

        stock_code = rem.get("stock_code", "")
        unified_row = unified_lookup.get(stock_code, {})
        d1_close = unified_row.get("d1_close")
        if d1_close is None or d1_close == 0:
            d1_close = foundation_prices.get(stock_code)
        if d1_close is None or d1_close == 0:
            d1_close = 0.0

        rr = rem.get("reward_risk", {})
        w1_mn1 = rem.get("w1_mn1_env", {})
        strategy = rem.get("strategy", {})
        strategy_id = strategy.get("strategy_id", "")

        # Compute stop
        stop_price = compute_stop_price(rem, float(d1_close) if d1_close else 0)

        # Exit rules by strategy
        exit_rules = {
            "vcp": [
                "假突破（hold_days ≤ 3 且 close < pivot_point）→ 全仓退出",
                "硬止损（pnl ≤ -6%）→ 全仓退出",
                "ATR 止损（close < entry - 2×ATR）→ 全仓退出",
                "技术止损（close < contraction_low × 0.99）→ 全仓退出",
                "时间退出（hold_days > 20 且 pnl < 5%）→ 全仓退出",
                "Trailing 止损（highest ≥ entry×1.05 且 current ≤ entry）→ 全仓退出",
            ],
            "ma2560": [
                "MA60 跌破 → 全仓退出",
                "MA25 跌破 → 全仓（或剩余半仓）退出",
                "盈利 ≥ 10% 且未全仓 → 全仓退出",
                "盈利 5-10% 且未半仓 → 半仓退出，止损移至成本价",
                "半仓后 close ≤ 成本价 → 剩余 trailing 退出",
            ],
            "bollinger_bandit": [
                "ATR 异常（current_ATR > 2×entry_ATR）→ 半仓退出",
                "中轨跌破（close < 50-day SMA）→ 全仓退出",
                "递减 MA 止损（close < exit_MA）→ 全仓退出",
                "上轨回撤半仓（prev_above_upper 且 close < bb_upper）→ 半仓退出",
                "时间退出（hold_days > 10 且 pnl < 5%）→ 全仓退出",
            ],
        }.get(strategy_id, ["按策略默认规则出场"])

        candidates_raw.append({
            "stock_code": stock_code,
            "stock_name": rem.get("stock_name", ""),
            "strategy_id": strategy_id,
            "signal_name": strategy.get("signal_name", ""),
            "signal_strength": strategy.get("signal_strength", 0),
            "strategy_fit": rem.get("strategy_environment_fit", ""),
            "fit_reasons": rem.get("fit_reasons", ""),
            "lifecycle_stage": rem.get("lifecycle_stage", ""),
            "maturity": rem.get("maturity", ""),
            # NOTE: RR fields removed — 阻力位止盈违背"让利润奔跑"原则
            "w1_mn1_label": w1_mn1.get("label", ""),
            "w1_mn1_desc": w1_mn1.get("description", ""),
            "d1_close": float(d1_close) if d1_close else 0,
            "stop_price": stop_price,
            "stop_method": f"策略默认止损 ¥{stop_price:.2f}",
            "exit_rules": exit_rules,
            "risk_note": unified_row.get("risk_note", "") or rem.get("local_stat_note", ""),
            "score": score_reminder(rem),
            "ifind": rem.get("ifind", {}),
        })

    # Sort by score descending
    candidates_raw.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Candidates after filtering: %d", len(candidates_raw))

    # 4. Top 5 execution params
    top5 = []
    for c in candidates_raw[:5]:
        entry = c["d1_close"]
        stop = c["stop_price"]

        # Dynamic per-trade risk based on candidate's strategy + fit level
        strategy_id = c["strategy_id"]
        fit_level = c.get("strategy_fit", "适配")
        strategy_implications = env.get("strategy_implications", {})
        strategy_info = strategy_implications.get(strategy_id, {})
        candidate_boost = strategy_info.get("factor", 1.0)

        # Industry MN1 coefficient
        sw_l1 = ""
        ifind = c.get("ifind", {}) or {}
        ind_ifind = ifind.get("industry", {}) or {}
        sw_l1 = str(ind_ifind.get("sw_l1", "") or "").strip()
        ind_mn1 = industry_mn1_map.get(sw_l1, {})
        industry_mn1_coeff = compute_industry_coeff_from_mn1(ind_mn1.get("mn1_score"))

        dyn = calculate_dynamic_position(
            market_phase=market_phase_key,
            strategy_boost=candidate_boost,
            macro_quadrant=macro_quadrant,
            fit_level=fit_level,
            macro_mn1_coeff=macro_mn1_coeff,
            industry_mn1_coeff=industry_mn1_coeff,
        )
        max_risk_pct = dyn["per_trade_risk_pct"] / 100.0

        pos = compute_position_size(entry, stop, capital, max_risk_pct=max_risk_pct)
        top5.append({
            **c,
            "entry_price": entry,
            "params": pos,
            "dynamic_risk_pct": dyn["per_trade_risk_pct"],
            "dynamic_reason": dyn["reason"],
        })

    # 5. Risk warnings
    warnings = generate_risk_warnings(candidates_raw)

    sop_data = {
        "date": date,
        "capital": capital,
        "generated_at": datetime.now().isoformat(),
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        "total_signals": len(reminders),
        "environment": env,
        "candidates": candidates_raw,
        "top5_execution_params": top5,
        "risk_warnings": warnings,
    }

    return sop_data


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily trading SOP")
    parser.add_argument("--date", required=True, help="Trade date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=1_000_000, help="Total capital (default 1,000,000)")
    parser.add_argument("--skip-html", action="store_true", help="Skip HTML output")
    args = parser.parse_args()

    date = args.date
    capital = args.capital

    sop = build_sop(date, capital)
    if "error" in sop:
        logger.error("Failed to build SOP: %s", sop["error"])
        return 1

    TRADING_SOP_DIR.mkdir(parents=True, exist_ok=True)

    # Write Markdown
    md_path = TRADING_SOP_DIR / f"daily_trading_sop_{date}.md"
    md_content = generate_md(sop, date)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info("Markdown: %s", md_path)

    # Write JSON
    json_path = TRADING_SOP_DIR / f"daily_trading_sop_{date}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sop, f, ensure_ascii=False, indent=2, default=str)
    logger.info("JSON: %s", json_path)

    # Write HTML
    if not args.skip_html:
        html_path = PUBLIC_DIR / f"daily_trading_sop_{date}.html"
        html_content = generate_html(sop, date)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info("HTML: %s", html_path)

    # Validation summary
    logger.info("=== SOP Validation ===")
    logger.info("Candidates: %d", len(sop["candidates"]))
    logger.info("Top 5 params generated: %d", len(sop["top5_execution_params"]))
    logger.info("Risk warnings: %d", len(sop["risk_warnings"]))
    for w in sop["risk_warnings"]:
        logger.info("  %s", w)

    return 0


if __name__ == "__main__":
    sys.exit(main())
