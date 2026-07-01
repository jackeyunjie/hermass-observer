#!/usr/bin/env python3
"""Weekly Observation Pipeline — 最小观察池摘要生成器。

直接读取 State Cube，生成 6 个等价 Agent 结构化观点，路由权重，写入账本，
输出 Markdown + JSON 作为本周主输出物。

Usage:
    python3 scripts/weekly_observation_pipeline.py --date 2026-06-05
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone, date
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

import duckdb

ROOT = Path(__file__).resolve().parent.parent
STATE_CUBE_DB = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
ROUTER_OUTPUT_DIR = ROOT / "outputs" / "router"
LEDGER_DIR = ROOT / "outputs" / "observation_ledger"
WEEKLY_OUTPUT_DIR = ROOT / "outputs" / "weekly_research"
AGENT_MEMORY_DB = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"


def _safe_float(v, default=0):
    """Safely convert a value to float, handling None/NaN."""
    if v is None:
        return default
    import math
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _json_safe(v):
    """Convert pandas/numpy values and non-finite floats to strict JSON values."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(item) for item in v]
    return v


# ──────────────────────────────────────────────────────────────
# Agent 1: Contraction Observer — 收缩突破观测
# ──────────────────────────────────────────────────────────────
def agent_contraction_observer(row: dict) -> dict:
    """基于 BB20/BB50 squeeze 状态判断收缩突破。"""
    d1_bb20_width = row.get("d1_bb20_width") or ""
    w1_bb20_width = row.get("w1_bb20_width") or ""
    d1_bb20_pos = row.get("d1_bb20_position") or ""
    w1_bb20_pos = row.get("w1_bb20_position") or ""
    d1_adx = _safe_float(row.get("d1_adx14"))

    is_squeeze_d1 = d1_bb20_width == "squeeze"
    is_squeeze_w1 = w1_bb20_width == "squeeze"
    is_breakout = (
        d1_bb20_pos in ("above_upper",) and not is_squeeze_d1
    )

    if is_breakout and is_squeeze_w1:
        stance = "support"
        confidence = min(90, 60 + int(d1_adx * 0.5))
        evidence = f"D1 突破 BB20 上轨（{d1_bb20_pos}），W1 仍在收缩（{w1_bb20_width}），大周期收缩后突破"
        concern = "突破后需确认量能配合，W1 收缩尚未解除意味着方向未完全确认"
        action = "关注"
    elif is_squeeze_d1 and is_squeeze_w1:
        stance = "neutral"
        confidence = 50
        evidence = f"D1 和 W1 均处于收缩状态（BB20 width=squeeze），能量蓄积中"
        concern = "收缩期方向不明，需等待突破信号"
        action = "观察"
    elif is_squeeze_d1:
        stance = "neutral"
        confidence = 40
        evidence = f"D1 收缩中（BB20 width=squeeze），W1 状态={w1_bb20_width}"
        concern = "仅 D1 收缩，大周期未同步，突破力度可能不足"
        action = "观察"
    elif d1_bb20_pos == "above_upper":
        stance = "support"
        confidence = min(80, 50 + int(d1_adx * 0.3))
        evidence = f"价格在 BB20 上轨之上（{d1_bb20_pos}），趋势向上"
        concern = "需确认不是短期超买"
        action = "关注"
    else:
        stance = "neutral"
        confidence = 30
        evidence = f"D1 BB20={d1_bb20_pos}/{d1_bb20_width}，W1 BB20={w1_bb20_pos}/{w1_bb20_width}，无明确收缩或突破信号"
        concern = "无收缩结构，不符合收缩突破策略前提"
        action = "观察"

    return {
        "agent_id": "contraction_observer",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Agent 2: M30 Observer — 盘中精细观察
# ──────────────────────────────────────────────────────────────
def agent_m30_observer(row: dict) -> dict:
    """基于 M30 ADX/BB 做盘中精细确认（只观察，不拍板）。"""
    import math
    m30_adx_raw = row.get("m30_adx14")
    m30_adx = m30_adx_raw if (m30_adx_raw is not None and not (isinstance(m30_adx_raw, float) and math.isnan(m30_adx_raw))) else 0
    m30_bb_pos = row.get("m30_bb20_position") or ""
    m30_bb_width = row.get("m30_bb20_width") or ""
    m30_close_raw = row.get("m30_close")
    m30_close = m30_close_raw if (m30_close_raw is not None and not (isinstance(m30_close_raw, float) and math.isnan(m30_close_raw))) else 0
    d1_close = row.get("d1_close") or 0

    if m30_adx == 0 and m30_bb_pos == "":
        return {
            "agent_id": "m30_observer",
            "stance": "data_missing",
            "confidence": 0,
            "evidence": "M30 数据不可用（ADX/BB 均为空）",
            "concern": "M30 盘中确认层缺失",
            "action": "观察",
        }

    if m30_adx > 30 and m30_bb_pos in ("above_upper", "above_middle"):
        stance = "support"
        confidence = min(85, 40 + int(m30_adx * 0.6))
        evidence = f"M30 ADX={m30_adx:.1f}（趋势明确），BB20={m30_bb_pos}，盘中动能向上"
        concern = "M30 周期短，单独信号不具备独立决策权重"
        action = "关注"
    elif m30_adx > 25 and m30_bb_width == "expanding":
        stance = "neutral"
        confidence = 45
        evidence = f"M30 ADX={m30_adx:.1f}（趋势形成中），BB20 {m30_bb_width}，波动扩大"
        concern = "趋势尚未充分确认，需 D1/W1 共振"
        action = "观察"
    elif m30_adx < 15:
        stance = "neutral"
        confidence = 25
        evidence = f"M30 ADX={m30_adx:.1f}（无趋势），BB20={m30_bb_pos}"
        concern = "M30 无方向，不适合精确入场"
        action = "观察"
    else:
        stance = "neutral"
        confidence = 35
        evidence = f"M30 ADX={m30_adx:.1f}，BB20={m30_bb_pos}/{m30_bb_width}"
        concern = "无明确突破或风险信号"
        action = "观察"

    return {
        "agent_id": "m30_observer",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Agent 3: Risk Guardian — 风险反驳（常驻）
# ──────────────────────────────────────────────────────────────
def agent_risk_guardian(row: dict) -> dict:
    """常驻反驳者，从 ATR/ADX/BB 位置寻找风险。"""
    risk_flags = []

    d1_atr = _safe_float(row.get("d1_atr14"))
    d1_close = _safe_float(row.get("d1_close"), 1)
    d1_adx = _safe_float(row.get("d1_adx14"))
    w1_adx = _safe_float(row.get("w1_adx14"))
    d1_plus_di = _safe_float(row.get("d1_plus_di_14"))
    d1_minus_di = _safe_float(row.get("d1_minus_di_14"))
    d1_bb_pos = row.get("d1_bb20_position") or ""
    w1_bb_pos = row.get("w1_bb20_position") or ""
    d1_bb_width = row.get("d1_bb20_width") or ""
    mn1_hex = row.get("mn1_state_hex") or ""
    w1_hex = row.get("w1_state_hex") or ""
    d1_hex = row.get("d1_state_hex") or ""

    atr_ratio = (d1_atr / d1_close * 100) if d1_close > 0 else 0

    # 风险检查 1: 高波动
    if atr_ratio > 5:
        risk_flags.append(f"高波动：ATR/Close={atr_ratio:.1f}%，短期回撤风险大")

    # 风险检查 2: ADX 过热
    if d1_adx > 60:
        risk_flags.append(f"D1 ADX={d1_adx:.1f} 过热，趋势可能接近尾声")

    # 风险检查 3: 多周期不一致
    states = [mn1_hex, w1_hex, d1_hex]
    ef_states = [s for s in states if s in ("E", "F")]
    if len(ef_states) < 2:
        risk_flags.append("多周期状态不一致：仅少数周期处于 E/F 活跃区")

    # 风险检查 4: 价格位置过高
    if d1_bb_pos == "above_upper" and w1_bb_pos == "above_upper":
        risk_flags.append("D1+W1 均在 BB 上轨之上，短期超买风险")

    # 风险检查 5: BB 扩张中（波动放大）
    if d1_bb_width == "expanding" and d1_adx < 20:
        risk_flags.append("BB 扩张但 ADX 低，可能是无序波动而非趋势")

    if len(risk_flags) >= 2:
        stance = "oppose"
        confidence = min(90, 40 + len(risk_flags) * 15)
        evidence = "；".join(risk_flags[:3])
        concern = risk_flags[0]
        action = "谨慎"
    elif len(risk_flags) == 1:
        stance = "neutral"
        confidence = 50
        evidence = risk_flags[0]
        concern = risk_flags[0]
        action = "观察"
    else:
        stance = "neutral"
        confidence = 30
        evidence = "当前未触发显著风险标记"
        concern = "低风险状态，但需持续监控"
        action = "观察"

    return {
        "agent_id": "risk_guardian",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
        "risk_flags": risk_flags,
    }


# ──────────────────────────────────────────────────────────────
# Agent 4: Market Analyst — 市场环境判断
# ──────────────────────────────────────────────────────────────
def agent_market_analyst(row: dict) -> dict:
    """基于多周期 MA 状态和 ADX 判断市场环境。"""
    d1_ma = row.get("d1_ma_state") or ""
    w1_ma = row.get("w1_ma_state") or ""
    d1_adx = _safe_float(row.get("d1_adx14"))
    w1_adx = _safe_float(row.get("w1_adx14"))
    d1_plus_di = _safe_float(row.get("d1_plus_di_14"))
    d1_minus_di = _safe_float(row.get("d1_minus_di_14"))

    # MA 排列分析
    bullish_ma = d1_ma in ("D1", "D2", "D3") and w1_ma in ("W1", "W2", "W3")
    bearish_ma = d1_ma in ("D5", "D6") and w1_ma in ("W5", "W6")
    aligned = d1_ma and w1_ma and d1_ma[0] == w1_ma[0]

    # DI 方向
    di_bullish = d1_plus_di > d1_minus_di and d1_plus_di > 20
    di_bearish = d1_minus_di > d1_plus_di and d1_minus_di > 20

    if bullish_ma and di_bullish:
        stance = "support"
        confidence = min(85, 55 + int(d1_adx * 0.3))
        evidence = f"MA 多头排列（D1={d1_ma}, W1={w1_ma}），+DI={d1_plus_di:.1f}>-DI={d1_minus_di:.1f}，趋势环境有利"
        concern = "趋势环境好不代表个股一定跟随，需确认个股自身结构"
        action = "关注"
    elif bearish_ma or di_bearish:
        stance = "oppose"
        confidence = min(75, 45 + int(abs(d1_minus_di - d1_plus_di) * 0.5))
        evidence = f"MA 偏空（D1={d1_ma}, W1={w1_ma}），-DI={d1_minus_di:.1f}，市场环境不利"
        concern = "大环境偏空时，即使个股结构好也应降低仓位"
        action = "谨慎"
    elif d1_adx < 15 and w1_adx < 15:
        stance = "neutral"
        confidence = 30
        evidence = f"D1 ADX={d1_adx:.1f}, W1 ADX={w1_adx:.1f}，双周期无趋势，市场处于震荡环境"
        concern = "无趋势环境下策略胜率下降"
        action = "观察"
    else:
        stance = "neutral"
        confidence = 40
        evidence = f"MA 排列中性（D1={d1_ma}, W1={w1_ma}），ADX D1={d1_adx:.1f}/W1={w1_adx:.1f}，环境不明确"
        concern = "市场环境不明朗，不适合重仓"
        action = "观察"

    return {
        "agent_id": "market_analyst",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Agent 5: Strategy Advisor — 策略适配判断
# ──────────────────────────────────────────────────────────────
def agent_strategy_advisor(row: dict) -> dict:
    """判断当前状态是否适配任何已知策略。"""
    mn1_hex = row.get("mn1_state_hex") or ""
    w1_hex = row.get("w1_state_hex") or ""
    d1_hex = row.get("d1_state_hex") or ""
    ef_count = row.get("ef_count") or 0
    d1_bb_width = row.get("d1_bb20_width") or ""
    w1_bb_width = row.get("w1_bb20_width") or ""
    d1_adx = _safe_float(row.get("d1_adx14"))

    strategies = []

    # 策略 1: 收缩突破
    if d1_bb_width == "squeeze" and ef_count >= 2:
        strategies.append("收缩突破（BB20 squeeze + EF 活跃）")

    # 策略 2: 多周期共振 E/F
    if ef_count >= 3:
        strategies.append(f"多周期共振（{ef_count} 个周期处于 E/F 活跃态）")

    # 策略 3: 趋势跟踪
    if d1_adx > 25 and d1_hex in ("E", "F"):
        strategies.append(f"趋势跟踪（D1 ADX={d1_adx:.1f}>25，状态={d1_hex}）")

    # 策略 4: MA 金叉/死叉
    d1_ma = row.get("d1_ma_state") or ""
    if d1_ma in ("D8",):
        strategies.append("MA 交叉转折（D1 MA 状态=D8 交叉）")

    if len(strategies) >= 2:
        stance = "support"
        confidence = min(85, 50 + len(strategies) * 12)
        evidence = f"适配 {len(strategies)} 个策略：" + "；".join(strategies[:3])
        concern = "多策略适配不代表多策略同时执行，需选择最优的一个"
        action = "关注"
    elif len(strategies) == 1:
        stance = "neutral"
        confidence = 50
        evidence = f"适配 1 个策略：{strategies[0]}"
        concern = "单一策略适配，信号强度有限"
        action = "观察"
    else:
        stance = "neutral"
        confidence = 25
        evidence = f"当前状态（MN1={mn1_hex}, W1={w1_hex}, D1={d1_hex}, EF={ef_count}）不特别适配已知策略"
        concern = "策略不适配时不应强行交易"
        action = "观察"

    return {
        "agent_id": "strategy_advisor",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Agent 6: Trend Observer — 趋势强度观测
# ──────────────────────────────────────────────────────────────
def agent_trend_observer(row: dict) -> dict:
    """基于多周期 ADX/DI 综合判断趋势强度。"""
    d1_adx = _safe_float(row.get("d1_adx14"))
    w1_adx = _safe_float(row.get("w1_adx14"))
    d1_plus = _safe_float(row.get("d1_plus_di_14"))
    d1_minus = _safe_float(row.get("d1_minus_di_14"))
    w1_plus = _safe_float(row.get("w1_plus_di_14"))
    w1_minus = _safe_float(row.get("w1_minus_di_14"))

    # 综合趋势评分
    d1_trend = d1_adx * (1 if d1_plus > d1_minus else -1)
    w1_trend = w1_adx * (1 if w1_plus > w1_minus else -1)
    composite = (d1_trend * 0.6 + w1_trend * 0.4)

    if composite > 30:
        stance = "support"
        confidence = min(85, 50 + int(composite * 0.4))
        evidence = (
            f"趋势强劲：D1 ADX={d1_adx:.1f}(+DI={d1_plus:.1f}/-DI={d1_minus:.1f})，"
            f"W1 ADX={w1_adx:.1f}(+DI={w1_plus:.1f}/-DI={w1_minus:.1f})，双周期向上"
        )
        concern = "强趋势也可能突然反转，注意 ADX 是否见顶"
        action = "关注"
    elif composite > 10:
        stance = "neutral"
        confidence = 45
        evidence = (
            f"趋势偏多：D1 ADX={d1_adx:.1f}，W1 ADX={w1_adx:.1f}，"
            f"方向偏正但未充分确认"
        )
        concern = "趋势中等强度，需更多确认"
        action = "观察"
    elif composite < -30:
        stance = "oppose"
        confidence = min(80, 50 + int(abs(composite) * 0.3))
        evidence = (
            f"趋势向下：D1 ADX={d1_adx:.1f}(-DI={d1_minus:.1f}主导)，"
            f"W1 ADX={w1_adx:.1f}(-DI={w1_minus:.1f}主导)"
        )
        concern = "下降趋势中不应抄底"
        action = "谨慎"
    else:
        stance = "neutral"
        confidence = 30
        evidence = f"趋势不明：D1 ADX={d1_adx:.1f}，W1 ADX={w1_adx:.1f}，综合评分={composite:.1f}"
        concern = "无趋势环境下信号噪音大"
        action = "观察"

    return {
        "agent_id": "trend_observer",
        "stance": stance,
        "confidence": confidence,
        "evidence": evidence,
        "concern": concern,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Router: 动态权重路由
# ──────────────────────────────────────────────────────────────
TIMEFRAME_WEIGHTS = {"MN1": 0.35, "W1": 0.30, "D1": 0.25, "M30": 0.10}
RESONANCE_BONUS = 0.20
CONFLICT_PENALTY = -0.15


def route_stock(row: dict, opinions: dict) -> dict:
    """对单只股票执行动态权重路由。"""
    mn1 = row.get("mn1_state_hex") or ""
    w1 = row.get("w1_state_hex") or ""
    d1 = row.get("d1_state_hex") or ""

    # 1. 周期层级评分
    tf_score = 0
    tf_detail = {}
    for tf, weight in TIMEFRAME_WEIGHTS.items():
        hex_val = {"MN1": mn1, "W1": w1, "D1": d1}.get(tf, "")
        is_ef = hex_val in ("E", "F")
        tf_detail[tf] = {"base_weight": weight, "is_ef": is_ef, "state_hex": hex_val}
        if is_ef:
            tf_score += weight

    # 2. Agent 共识分析
    support = [aid for aid, op in opinions.items() if op["stance"] == "support"]
    oppose = [aid for aid, op in opinions.items() if op["stance"] == "oppose"]
    neutral = [aid for aid, op in opinions.items() if op["stance"] == "neutral"]
    missing = [aid for aid, op in opinions.items() if op["stance"] == "data_missing"]

    consensus_adjust = 0
    if len(support) >= 3:
        consensus_adjust += RESONANCE_BONUS
    elif len(support) >= 2:
        consensus_adjust += RESONANCE_BONUS * 0.6

    if "risk_guardian" in oppose:
        consensus_adjust += CONFLICT_PENALTY * 0.8
    if len(oppose) >= 2:
        consensus_adjust += CONFLICT_PENALTY

    core_missing = {"contraction_observer", "m30_observer"}.issubset(set(missing))
    if core_missing:
        consensus_adjust += CONFLICT_PENALTY * 0.5

    # 3. M30 微调
    m30_fine_tune = 0
    m30_op = opinions.get("m30_observer", {})
    if m30_op.get("stance") == "support":
        m30_fine_tune = 0.05
    elif m30_op.get("stance") == "oppose":
        m30_fine_tune = -0.05

    # 4. 最终权重
    final_weight = tf_score + consensus_adjust + m30_fine_tune
    final_weight = max(0.0, min(1.0, final_weight))

    # 5. 冲突/共振标记
    is_resonance = len(support) >= 3 and "risk_guardian" not in oppose
    is_conflict = len(support) >= 1 and "risk_guardian" in oppose

    # 6. 观察结论
    has_risk_oppose = "risk_guardian" in oppose
    if final_weight >= 0.7 and is_resonance:
        conclusion = "strong_observation"
        action = "重点观察"
    elif final_weight >= 0.5 and len(support) >= 2:
        conclusion = "moderate_observation"
        action = "适度观察"
    elif has_risk_oppose:
        conclusion = "risk_warning"
        action = "风险提醒"
    elif core_missing and len(support) == 0:
        conclusion = "neutral"
        action = "数据不完整，保持观察"
    else:
        conclusion = "neutral"
        action = "无特别信号"

    return {
        "tf_weights": tf_detail,
        "tf_score": round(tf_score, 3),
        "consensus_adjust": round(consensus_adjust, 3),
        "m30_fine_tune": round(m30_fine_tune, 3),
        "final_weight": round(final_weight, 3),
        "support_agents": support,
        "oppose_agents": oppose,
        "neutral_agents": neutral,
        "data_missing_agents": missing,
        "resonance": is_resonance,
        "conflict": is_conflict,
        "conclusion": conclusion,
        "action": action,
    }


# ──────────────────────────────────────────────────────────────
# Ledger: 账本写入
# ──────────────────────────────────────────────────────────────
def ensure_ledger_schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS agent_judgments (
            agent_id VARCHAR NOT NULL,
            judgment_id VARCHAR PRIMARY KEY,
            judgment_date DATE NOT NULL,
            judgment_type VARCHAR NOT NULL,
            judgment_content JSON,
            confidence DOUBLE,
            factors_used JSON,
            context_snapshot JSON
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_aj_agent ON agent_judgments(agent_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_aj_date ON agent_judgments(judgment_date)")


def write_ledger(records: list[dict], as_of_date: date, rendered_at: str):
    """写入 AgentMemory.duckdb 和 JSON 备份。"""
    os.makedirs(AGENT_MEMORY_DB.parent, exist_ok=True)
    os.makedirs(LEDGER_DIR, exist_ok=True)

    con = duckdb.connect(str(AGENT_MEMORY_DB))
    ensure_ledger_schema(con)

    con.execute(
        """
        DELETE FROM agent_judgments
        WHERE judgment_date = ?
          AND judgment_type = 'weekly_observation'
          AND agent_id = 'WeeklyObservationPipeline'
        """,
        [as_of_date],
    )

    written = 0
    for r in records:
        judgment_id = str(
            uuid5(
                NAMESPACE_URL,
                f"weekly-observation:{as_of_date}:{r.get('stock_code', '')}",
            )
        )
        con.execute("""
            INSERT INTO agent_judgments
            (agent_id, judgment_id, judgment_date, judgment_type,
             judgment_content, confidence, factors_used, context_snapshot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r.get("agent_id", "WeeklyPipeline"),
            judgment_id,
            as_of_date,
            "weekly_observation",
            json.dumps(r, ensure_ascii=False, default=str),
            r.get("confidence", 0.5),
            json.dumps({"source": "weekly_observation_pipeline", "version": "1.0"}, ensure_ascii=False),
            json.dumps({"state_date": str(as_of_date), "ledger_version": "phase3_mvp"}, ensure_ascii=False),
        ))
        written += 1

    con.commit()
    con.close()

    backup_path = LEDGER_DIR / f"observation_ledger_{as_of_date.strftime('%Y%m%d')}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump({
            "state_date": str(as_of_date),
            "record_count": written,
            "records": records,
            "written_at": rendered_at,
        }, f, ensure_ascii=False, indent=2)

    print(f"[ledger] 写入 {written} 条到 AgentMemory，备份: {backup_path}")


# ──────────────────────────────────────────────────────────────
# Markdown Renderer
# ──────────────────────────────────────────────────────────────

# Hermass State 中文映射
STATE_MEANING = {
    "E": "突破活跃期",
    "F": "回踩确认期",
    "A": "多头加速",
    "B": "多头减速",
    "C": "空头加速",
    "D": "空头减速",
}


# ──────────────────────────────────────────────────────────────
# Consumer-grade Markdown Renderer (v2)
# ──────────────────────────────────────────────────────────────

def _pick_top2(router_results: list[dict]) -> list[dict]:
    """选出本周最该盯的 2 只：strong 优先，不足从 moderate 补。"""
    strong = [r for r in router_results if r["conclusion"] == "strong_observation"]
    moderate = [r for r in router_results if r["conclusion"] == "moderate_observation"]
    candidates = strong + moderate
    return candidates[:2]


def _pick_risk1(router_results: list[dict], stock_map: dict) -> dict | None:
    """选出本周最值得警惕的 1 只：Risk Guardian oppose > risk_flags 多 > 权重高。"""
    scored = []
    for r in router_results:
        code = r["stock_code"]
        sd = stock_map.get(code, {})
        opinions = sd.get("opinions", {})
        rg = opinions.get("risk_guardian", {})
        flags = rg.get("risk_flags", [])
        is_oppose = rg.get("stance") == "oppose"
        # 打分：oppose +10，每条 flag +2，权重越高越需要警惕（因为强信号股的风险更值得盯）
        score = (10 if is_oppose else 0) + len(flags) * 2 + r["final_weight"]
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


def _stock_one_liner(r: dict, opinions: dict) -> str:
    """一句话结论。"""
    if r.get("resonance"):
        return f"多视角共振，Router权重 {r['final_weight']:.0%}"
    elif r.get("conflict"):
        return f"趋势强但被 Risk Guardian 反驳，权重 {r['final_weight']:.0%}"
    else:
        return f"Router权重 {r['final_weight']:.0%}，有信号但强度一般"


def _stock_watch_for(r: dict, opinions: dict) -> str:
    """本周最关键观察点——只取最核心的一句看多证据。"""
    # 优先级：策略适配 > 趋势强度 > 市场环境 > 收缩突破
    for aid in ["strategy_advisor", "trend_observer", "market_analyst", "contraction_observer"]:
        if aid in r.get("support_agents", []):
            ev = opinions.get(aid, {}).get("evidence", "")
            if ev:
                # 截短到 60 字，去掉冗余前缀
                ev = ev.replace("趋势强劲：", "").replace("MA 多头排列（", "MA多头 ").replace("），", " ")
                if len(ev) > 60:
                    ev = ev[:57] + "..."
                return ev
    return "跟踪多周期共振是否延续"


def _stock_invalid_when(r: dict, opinions: dict) -> str:
    """什么情况下判断失效。"""
    rg = opinions.get("risk_guardian", {})
    flags = rg.get("risk_flags", [])
    if flags:
        # 取最核心的风险
        core = flags[0]
        if len(core) > 55:
            core = core[:52] + "..."
        return core
    for aid in r.get("oppose_agents", []):
        ev = opinions.get(aid, {}).get("evidence", "")
        if ev:
            if len(ev) > 55:
                ev = ev[:52] + "..."
            return ev
    return "Router权重跌破 0.5 或关键周期退出 E/F"


def _risk_verification_signal(opinions: dict) -> str:
    """风险被验证的具体技术信号。"""
    rg = opinions.get("risk_guardian", {})
    flags = rg.get("risk_flags", [])
    # 根据风险类型给出验证信号
    for flag in flags:
        if "ADX" in flag and "过热" in flag:
            return "ADX 从高位回落且收盘价跌破 BB20 中轨"
        if "BB 上轨" in flag or "超买" in flag:
            return "收盘价跌破 BB20 中轨或连续 2 日收阴"
        if "高波动" in flag or "ATR" in flag:
            return "单日跌幅 > ATR 均值或跌破前 3 日低点"
    return "Router权重跌破 0.5 或 Risk Guardian 立场升级"


def render_markdown(
    stocks_data: list[dict],
    router_results: list[dict],
    target_date: str,
    generated_at: str,
) -> str:
    """生成消费级周观察简报：先结论，后证据，30 秒内抓到重点。"""

    stock_map = {s["stock_code"]: s for s in stocks_data}
    agent_names = {
        "contraction_observer": "收缩突破",
        "m30_observer": "M30 盘中",
        "risk_guardian": "风险反驳",
        "market_analyst": "市场环境",
        "strategy_advisor": "策略适配",
        "trend_observer": "趋势强度",
    }

    # 分类
    strong = [r for r in router_results if r["conclusion"] == "strong_observation"]
    moderate = [r for r in router_results if r["conclusion"] == "moderate_observation"]
    risk_warn = [r for r in router_results if r["conclusion"] == "risk_warning"]

    # 选股
    top2 = _pick_top2(router_results)
    risk1 = _pick_risk1(router_results, stock_map)
    picked_codes = {r["stock_code"] for r in top2}
    if risk1:
        picked_codes.add(risk1["stock_code"])
    others = [r for r in router_results if r["stock_code"] not in picked_codes]

    lines = []
    lines.append(f"## 本周观察简报")
    lines.append(f"")
    lines.append(f"**数据日期**：{target_date}　|　**观察池**：{len(stocks_data)} 只　|　**生成**：{generated_at}")
    lines.append(f"")

    # ── 1. 一句话结论 ──
    lines.append("---")
    lines.append("")
    lines.append("### 1. 本周一句话结论")
    lines.append("")
    # 动态生成一句话结论
    if strong:
        strong_names = "、".join([r["stock_code"] for r in strong[:2]])
        core_msg = f"观察池 {len(stocks_data)} 只全部 EF 活跃，其中 {strong_names} 等多视角共振，重点跟踪延续；"
    else:
        core_msg = f"观察池 {len(stocks_data)} 只 EF 活跃，但无强共振信号，"
    # 找共性风险
    all_flags = []
    for r in router_results:
        rg = stock_map.get(r["stock_code"], {}).get("opinions", {}).get("risk_guardian", {})
        all_flags.extend(rg.get("risk_flags", []))
    if any("ADX" in f and "过热" in f for f in all_flags):
        core_msg += "整体需防 ADX 过热后的高波动回撤。"
    elif all_flags:
        core_msg += "整体波动偏高，注意短期回撤风险。"
    else:
        core_msg += "风险标记较少，结构相对干净。"
    lines.append(core_msg)
    lines.append("")

    # ── 2. 本周只看这 2 只 ──
    lines.append("---")
    lines.append("")
    lines.append("### 2. 本周只看这 2 只")
    lines.append("")
    lines.append("| 代码 | 收盘价 | 一句话结论 | 本周看点 | 失效条件 |")
    lines.append("|------|--------|-----------|----------|----------|")
    for r in top2:
        code = r["stock_code"]
        sd = stock_map.get(code, {})
        row = sd.get("raw", {})
        opinions = sd.get("opinions", {})
        close = row.get("d1_close", 0)
        oneliner = _stock_one_liner(r, opinions)
        watch = _stock_watch_for(r, opinions)
        invalid = _stock_invalid_when(r, opinions)
        lines.append(f"| {code} | ¥{close:.2f} | {oneliner} | {watch} | {invalid} |")
    lines.append("")

    # ── 3. 本周风险提醒 1 只 ──
    lines.append("---")
    lines.append("")
    lines.append("### 3. 本周风险提醒 1 只")
    lines.append("")
    if risk1:
        code = risk1["stock_code"]
        sd = stock_map.get(code, {})
        row = sd.get("raw", {})
        opinions = sd.get("opinions", {})
        close = row.get("d1_close", 0)
        rg = opinions.get("risk_guardian", {})
        risk_flags = rg.get("risk_flags", [])

        # 为什么看起来强
        looks_strong = _stock_watch_for(risk1, opinions)
        # 风险反驳
        risk_concern = "；".join(risk_flags[:2]) if risk_flags else "Risk Guardian 未发现显著风险"
        if len(risk_concern) > 80:
            risk_concern = risk_concern[:77] + "..."
        # 验证信号
        verify_signal = _risk_verification_signal(opinions)

        lines.append(f"**{code}**　¥{close:.2f}")
        lines.append("")
        lines.append(f"- **为什么看起来强**：{looks_strong}")
        lines.append(f"- **风险反驳点**：{risk_concern}")
        lines.append(f"- **哪个信号出现说明风险被验证**：{verify_signal}")
        lines.append("")
    else:
        lines.append("本周观察池内暂无明确风险提醒标的。")
        lines.append("")

    # ── 4. 其余观察池简表 ──
    if others:
        lines.append("---")
        lines.append("")
        lines.append("### 4. 其余观察池简表")
        lines.append("")
        lines.append("| 代码 | 收盘价 | Router权重 | 核心状态 | 风险标记 |")
        lines.append("|------|--------|-----------|----------|----------|")
        for r in others:
            code = r["stock_code"]
            sd = stock_map.get(code, {})
            row = sd.get("raw", {})
            opinions = sd.get("opinions", {})
            close = row.get("d1_close", 0)
            mn1 = row.get("mn1_state_hex", "?")
            w1 = row.get("w1_state_hex", "?")
            d1 = row.get("d1_state_hex", "?")
            core_state = f"MN1={mn1},W1={w1},D1={d1}"
            rg = opinions.get("risk_guardian", {})
            flags = rg.get("risk_flags", [])
            risk_label = "；".join(flags[:2]) if flags else "—"
            if len(risk_label) > 30:
                risk_label = risk_label[:27] + "..."
            lines.append(
                f"| {code} | ¥{close:.2f} | {r['final_weight']:.0%} | {core_state} | {risk_label} |"
            )
        lines.append("")

    # ── 5. 方法说明（压缩版） ──
    lines.append("---")
    lines.append("")
    lines.append("### 5. 方法说明")
    lines.append("")
    lines.append(
        "- **多周期状态**：MN1(月线)/W1(周线)/D1(日线) 独立判断 E(突破)/F(回踩)，≥2 周期同步才入选"
    )
    lines.append(
        "- **6 视角**：收缩突破、M30 盘中、风险反驳、市场环境、策略适配、趋势强度——各给独立意见"
    )
    lines.append(
        "- **Risk Guardian**：常驻反驳者，专门找过热、高波动、超买；触发风险时会降低 Router 权重"
    )
    lines.append(
        "- **Router 权重**：MN1(35%)>W1(30%)>D1(25%)>M30(10%)，共振加分，Risk 反驳减分，0-1 定观察级别"
    )
    lines.append("")
    lines.append(f"*本报告由 weekly_observation_pipeline 自动生成，不构成投资建议。*")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Main Pipeline
# ──────────────────────────────────────────────────────────────
def run_pipeline(
    target_date: str,
    stock_codes: list[str] | None = None,
    top_n: int = 5,
    output_label: str | None = None,
    stable: bool = True,
):
    """执行完整 pipeline。"""
    print(f"=== Weekly Observation Pipeline: {target_date} ===\n")

    # 1. 读取 State Cube
    con = duckdb.connect(str(STATE_CUBE_DB), read_only=True)

    if stock_codes:
        code_filter = " AND stock_code IN (" + ",".join(f"'{c}'" for c in stock_codes) + ")"
    else:
        code_filter = ""

    df = con.execute(f"""
        SELECT *
        FROM state_cube
        WHERE state_date = DATE '{target_date}'
          AND ef_count >= 2
          {code_filter}
        ORDER BY ef_count DESC, d1_close DESC
        LIMIT {top_n if not stock_codes else 100}
    """).fetchdf()
    con.close()

    if df.empty:
        print(f"[pipeline] {target_date} 无候选数据")
        return

    print(f"[pipeline] 候选池: {len(df)} 只")

    # 2. 逐只股票生成 6 Agent 意见 + 路由
    stocks_data = []
    router_results = []
    ledger_records = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        code = row_dict["stock_code"]

        # 6 Agent 意见
        opinions = {
            "contraction_observer": agent_contraction_observer(row_dict),
            "m30_observer": agent_m30_observer(row_dict),
            "risk_guardian": agent_risk_guardian(row_dict),
            "market_analyst": agent_market_analyst(row_dict),
            "strategy_advisor": agent_strategy_advisor(row_dict),
            "trend_observer": agent_trend_observer(row_dict),
        }

        # Router
        routed = route_stock(row_dict, opinions)
        routed["stock_code"] = code

        stocks_data.append({
            "stock_code": code,
            "raw": row_dict,
            "opinions": opinions,
            "routed": routed,
        })
        router_results.append(routed)

        # Ledger record
        ledger_records.append({
            "agent_id": "WeeklyObservationPipeline",
            "stock_code": code,
            "state_date": target_date,
            "direction": routed["conclusion"],
            "confidence": routed["final_weight"],
            "rationale": routed["action"],
            "risk_flags": opinions["risk_guardian"].get("risk_flags", []),
            "key_states": {
                "MN1": row_dict.get("mn1_state_hex"),
                "W1": row_dict.get("w1_state_hex"),
                "D1": row_dict.get("d1_state_hex"),
                "ef_count": row_dict.get("ef_count"),
            },
            "support_agents": routed["support_agents"],
            "oppose_agents": routed["oppose_agents"],
            "resonance": routed["resonance"],
            "conflict": routed["conflict"],
            "opinions": opinions,
        })

    # 排序
    router_results.sort(key=lambda x: x["final_weight"], reverse=True)

    # 3. 生成 Markdown
    report_label = output_label or target_date.replace("-", "")
    if stable:
        generated_at = f"{report_label} 00:00 UTC"
    else:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md_content = render_markdown(stocks_data, router_results, target_date, generated_at)

    # 4. 生成 JSON
    json_output = {
        "title": "State Cube 最小观察池摘要",
        "target_date": target_date,
        "generated_at": generated_at,
        "pipeline_version": "1.0",
        "pool_size": len(stocks_data),
        "summary": {
            "strong_observation": sum(1 for r in router_results if r["conclusion"] == "strong_observation"),
            "moderate_observation": sum(1 for r in router_results if r["conclusion"] == "moderate_observation"),
            "risk_warning": sum(1 for r in router_results if r["conclusion"] == "risk_warning"),
            "neutral": sum(1 for r in router_results if r["conclusion"] == "neutral"),
        },
        "stocks": [],
    }

    for sd in stocks_data:
        row = sd["raw"]
        json_output["stocks"].append({
            "stock_code": sd["stock_code"],
            "state": {
                "MN1": _json_safe(row.get("mn1_state_hex")),
                "W1": _json_safe(row.get("w1_state_hex")),
                "D1": _json_safe(row.get("d1_state_hex")),
                "ef_count": _json_safe(row.get("ef_count")),
                "d1_close": _json_safe(row.get("d1_close")),
                "d1_adx14": _json_safe(row.get("d1_adx14")),
                "w1_adx14": _json_safe(row.get("w1_adx14")),
                "d1_bb20_position": _json_safe(row.get("d1_bb20_position")),
                "d1_bb20_width": _json_safe(row.get("d1_bb20_width")),
                "w1_bb20_position": _json_safe(row.get("w1_bb20_position")),
                "w1_bb20_width": _json_safe(row.get("w1_bb20_width")),
                "d1_ma_state": _json_safe(row.get("d1_ma_state")),
                "w1_ma_state": _json_safe(row.get("w1_ma_state")),
                "m30_adx14": _json_safe(row.get("m30_adx14")),
                "m30_bb20_position": _json_safe(row.get("m30_bb20_position")),
            },
            "agent_opinions": {
                aid: {
                    "stance": op["stance"],
                    "confidence": op["confidence"],
                    "evidence": op["evidence"],
                    "concern": op["concern"],
                    "action": op["action"],
                    **({"risk_flags": op["risk_flags"]} if "risk_flags" in op else {}),
                }
                for aid, op in sd["opinions"].items()
            },
            "routing": {
                "tf_score": sd["routed"]["tf_score"],
                "consensus_adjust": sd["routed"]["consensus_adjust"],
                "m30_fine_tune": sd["routed"]["m30_fine_tune"],
                "final_weight": sd["routed"]["final_weight"],
                "support_agents": sd["routed"]["support_agents"],
                "oppose_agents": sd["routed"]["oppose_agents"],
                "resonance": sd["routed"]["resonance"],
                "conflict": sd["routed"]["conflict"],
                "conclusion": sd["routed"]["conclusion"],
                "action": sd["routed"]["action"],
            },
        })

    # 5. 写入文件
    os.makedirs(WEEKLY_OUTPUT_DIR, exist_ok=True)
    date_str = report_label

    md_path = WEEKLY_OUTPUT_DIR / f"weekly_observation_{date_str}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"[output] Markdown: {md_path}")

    json_path = WEEKLY_OUTPUT_DIR / f"weekly_observation_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(json_output), f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[output] JSON: {json_path}")

    # 6. 写入 Router 输出（给 Ledger 使用）
    os.makedirs(ROUTER_OUTPUT_DIR, exist_ok=True)
    router_path = ROUTER_OUTPUT_DIR / f"router_decisions_{date_str}.json"
    with open(router_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(router_results), f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[output] Router: {router_path}")

    # 7. 写入 Ledger
    write_ledger(ledger_records, date.fromisoformat(target_date), generated_at)

    # 8. 统计摘要
    print(f"\n{'='*60}")
    print(f"Pipeline 完成:")
    print(f"  候选池: {len(stocks_data)} 只")
    print(f"  重点观察: {json_output['summary']['strong_observation']}")
    print(f"  适度观察: {json_output['summary']['moderate_observation']}")
    print(f"  风险提醒: {json_output['summary']['risk_warning']}")
    print(f"  中性: {json_output['summary']['neutral']}")

    return json_output


def main():
    parser = argparse.ArgumentParser(description="Weekly Observation Pipeline")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--stocks", nargs="*", help="指定股票代码列表")
    parser.add_argument("--top-n", type=int, default=10, help="自动选取 top N 只")
    parser.add_argument("--output-label", default="", help="输出文件标签日期，如 20260608")
    parser.add_argument(
        "--unstable-timestamp",
        action="store_true",
        help="使用真实生成时间而不是稳定时间戳",
    )
    args = parser.parse_args()

    run_pipeline(
        target_date=args.date,
        stock_codes=args.stocks,
        top_n=args.top_n,
        output_label=args.output_label or None,
        stable=not args.unstable_timestamp,
    )


if __name__ == "__main__":
    main()
