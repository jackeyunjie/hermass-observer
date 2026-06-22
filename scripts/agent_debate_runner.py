"""Agent Debate Runner — queries State Cube and produces 6-agent structured opinions.

Phase 2 MOE architecture: each agent reads market-wide aggregates from the State Cube
and produces a structured opinion (verdict, evidence, risk). No LLM calls needed —
all reasoning is rule-based from multi-timeframe indicator data.

Output: JSON with 6 agent opinions, designed to feed into debate_dashboard.html template.
"""
import duckdb
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_CUBE = ROOT / "outputs" / "state_cube" / "state_cube.duckdb"
OUTPUT = ROOT / "outputs" / "debate" / "agent_debate_latest.json"


def _query_cube(latest_date: str, where: str = "1=1", limit: int = 50) -> list[dict]:
    con = duckdb.connect(str(STATE_CUBE), read_only=True)
    rows = con.execute(
        f"""
        SELECT stock_code, mn1_state_hex, w1_state_hex, d1_state_hex, ef_count,
               w1_ma_state, d1_ma_state,
               w1_bb20_position, d1_bb20_position, w1_bb20_width, d1_bb20_width,
               w1_bb50_position, d1_bb50_position,
               ROUND(w1_atr14, 2) AS w1_atr14, ROUND(d1_atr14, 2) AS d1_atr14,
               ROUND(w1_adx14, 1) AS w1_adx14, ROUND(d1_adx14, 1) AS d1_adx14,
               ROUND(w1_plus_di_14, 1) AS w1_plus_di_14,
               ROUND(d1_plus_di_14, 1) AS d1_plus_di_14,
               ROUND(w1_minus_di_14, 1) AS w1_minus_di_14,
               ROUND(d1_minus_di_14, 1) AS d1_minus_di_14,
               ROUND(d1_close, 2) AS d1_close, ROUND(w1_close, 2) AS w1_close,
               future_r5, future_r20
        FROM state_cube
        WHERE state_date = '{latest_date}'
          AND {where}
        ORDER BY ef_count DESC, d1_adx14 DESC
        LIMIT {limit}
    """
    ).fetchall()
    cols = [
        "stock_code", "mn1_state_hex", "w1_state_hex", "d1_state_hex", "ef_count",
        "w1_ma_state", "d1_ma_state", "w1_bb20_position", "d1_bb20_position",
        "w1_bb20_width", "d1_bb20_width", "w1_bb50_position", "d1_bb50_position",
        "w1_atr14", "d1_atr14", "w1_adx14", "d1_adx14",
        "w1_plus_di_14", "d1_plus_di_14", "w1_minus_di_14", "d1_minus_di_14",
        "d1_close", "w1_close", "future_r5", "future_r20",
    ]
    return [dict(zip(cols, row)) for row in rows]


def _market_aggregates(latest_date: str) -> dict:
    con = duckdb.connect(str(STATE_CUBE), read_only=True)
    row = con.execute(f"""
        SELECT
            COUNT(*) AS total,
            ROUND(AVG(d1_adx14), 1) AS avg_d1_adx,
            ROUND(AVG(w1_adx14), 1) AS avg_w1_adx,
            ROUND(AVG(CASE WHEN d1_plus_di_14 > d1_minus_di_14 THEN 1.0 ELSE 0.0 END) * 100, 1) AS d1_bull_pct,
            ROUND(AVG(CASE WHEN w1_plus_di_14 > w1_minus_di_14 THEN 1.0 ELSE 0.0 END) * 100, 1) AS w1_bull_pct,
            COUNT(CASE WHEN ef_count >= 2 THEN 1 END) AS ef2_count,
            COUNT(CASE WHEN ef_count >= 3 THEN 1 END) AS ef3_count,
            COUNT(CASE WHEN d1_bb20_position = 'above_upper' THEN 1 END) AS above_bb,
            COUNT(CASE WHEN d1_bb20_position = 'below_lower' THEN 1 END) AS below_bb,
            ROUND(AVG(d1_atr14 / NULLIF(d1_close, 0)) * 100, 1) AS avg_atr_pct,
            COUNT(CASE WHEN d1_adx14 >= 40 AND d1_plus_di_14 > d1_minus_di_14 THEN 1 END) AS strong_momentum,
            COUNT(CASE WHEN d1_adx14 >= 70 THEN 1 END) AS extreme_adx,
            COUNT(CASE WHEN d1_adx14 >= 30 AND d1_minus_di_14 > d1_plus_di_14 THEN 1 END) AS bearish_div,
            COUNT(CASE WHEN d1_bb20_position = 'above_upper' AND d1_adx14 < w1_adx14 THEN 1 END) AS fake_breakout,
            COUNT(CASE WHEN mn1_state_hex NOT IN ('E', 'F') AND ef_count >= 2 THEN 1 END) AS mn1_weak_ef2
        FROM state_cube
        WHERE state_date = '{latest_date}' AND d1_close > 0
    """).fetchone()
    return {
        "total_stocks": row[0], "avg_d1_adx": row[1], "avg_w1_adx": row[2],
        "d1_bull_pct": row[3], "w1_bull_pct": row[4],
        "ef2_count": row[5], "ef3_count": row[6],
        "d1_above_bb": row[7], "d1_below_bb": row[8],
        "avg_atr_pct": row[9],
        "strong_momentum": row[10], "extreme_adx": row[11],
        "bearish_div": row[12], "fake_breakout": row[13],
        "mn1_weak_ef2": row[14],
    }


def _trend_opinion(stocks: list[dict], market: dict) -> dict:
    ef2_count = market["ef2_count"]
    ef3_count = market["ef3_count"]
    pct_ef2 = ef2_count / max(market["total_stocks"], 1) * 100
    hex_patterns = {}
    for s in stocks:
        key = f"{s['mn1_state_hex']}-{s['w1_state_hex']}-{s['d1_state_hex']}"
        hex_patterns[key] = hex_patterns.get(key, 0) + 1
    top_pattern = max(hex_patterns, key=hex_patterns.get) if hex_patterns else "?"
    return {
        "agent": "趋势 Agent", "role": "周线趋势判断",
        "verdict": "偏多" if pct_ef2 >= 8 else "中性",
        "verdict_color": "green" if pct_ef2 >= 10 else "yellow",
        "conclusion": (
            f"EF≥2 标的 {ef2_count} 只（{pct_ef2:.0f}%），EF=3 共 {ef3_count} 只，"
            f"主导形态 {top_pattern}（高 ADX 样本），MN1/W1 多头排列"
        ),
        "evidence": [
            f"EF≥2 标的 {ef2_count} 只（占比 {pct_ef2:.0f}%），EF=3 共 {ef3_count} 只",
            f"三周期主导形态 {top_pattern}（高 ADX 样本 {hex_patterns.get(top_pattern, 0)} 只）",
            f"市场 avg_w1_ADX {market['avg_w1_adx']}，趋势明确度 {'强' if market['avg_w1_adx'] > 30 else '一般'}",
        ],
        "risk": f"EF=3 标的 {ef3_count} 只{'，热度偏高需关注拥挤' if ef3_count > 200 else ''}。若周线MA跌破则趋势逆转",
    }


def _momentum_opinion(stocks: list[dict], market: dict) -> dict:
    strong = market["strong_momentum"]
    avg_adx = market["avg_d1_adx"]
    adx_level = "强势" if avg_adx >= 35 else ("中等偏强" if avg_adx >= 25 else "偏弱")
    bull_pct = market["d1_bull_pct"]
    return {
        "agent": "动量 Agent", "role": "日线动量判断",
        "verdict": "偏多" if bull_pct >= 50 else "中性",
        "verdict_color": "green" if bull_pct >= 60 else ("yellow" if bull_pct >= 40 else "red"),
        "conclusion": f"D1 ADX 均值 {avg_adx}（{adx_level}），全市场 ADX≥40 正向动量 {strong} 只，+DI > -DI 占比 {bull_pct}%",
        "evidence": [
            f"全市场 ADX≥40 且 +DI > -DI 共 {strong} 只（正向动量）",
            f"D1 ADX 均值 {avg_adx}，W1 ADX 均值 {market['avg_w1_adx']}",
            f"全市场 +DI > -DI 占比 {bull_pct}%（日线动量方向）",
        ],
        "risk": f"{strong} 只 D1 动量强劲需关注持续性" if strong > 500 else "动量分布正常，关注个别标的目标回踩",
    }


def _volatility_opinion(stocks: list[dict], market: dict) -> dict:
    above_bb = market["d1_above_bb"]
    below_bb = market["d1_below_bb"]
    avg_atr = market["avg_atr_pct"]
    extreme = above_bb + below_bb
    atr_level = "高波动" if avg_atr >= 8 else ("中等波动" if avg_atr >= 4 else "低波动")
    risk_items = []
    if above_bb > 200:
        risk_items.append(f"{above_bb} 只突破 BB 上轨，存在回落风险")
    if below_bb > 200:
        risk_items.append(f"{below_bb} 只跌破 BB 下轨，存在超跌反弹或继续下行风险")
    if avg_atr >= 8:
        risk_items.append(f"高 ATR%({avg_atr}%) 环境，止损需适当放宽")
    return {
        "agent": "波动率 Agent", "role": "波动率环境判断",
        "verdict": "观察" if extreme > 300 else "正常",
        "verdict_color": "yellow" if extreme > 300 else "green",
        "conclusion": f"ATR/收盘均值 {avg_atr}%（{atr_level}），BB 极端位置 {extreme} 只（上轨 {above_bb} / 下轨 {below_bb}）",
        "evidence": [
            f"BB 上轨突破 {above_bb} 只，下轨跌破 {below_bb} 只",
            f"全市场 avg_ATR% = {avg_atr}%（{atr_level}环境）",
        ],
        "risk": "；".join(risk_items) if risk_items else "波动率环境正常，无极端信号",
    }


def _boundary_opinion(stocks: list[dict], market: dict) -> dict:
    above_d1_bb = [s for s in stocks if s["d1_bb20_position"] == "above_upper"]
    below_d1_bb = [s for s in stocks if s["d1_bb20_position"] == "below_lower"]
    d1_ma_above = [s for s in stocks if "D7" in str(s.get("d1_ma_state", "")) or "D6" in str(s.get("d1_ma_state", ""))]
    return {
        "agent": "边界 Agent", "role": "支撑/阻力位置判断",
        "verdict": "谨慎" if len(above_d1_bb) > 50 else "正常",
        "verdict_color": "yellow" if len(above_d1_bb) > 50 else "green",
        "conclusion": (
            f"日线 BB 上轨外 {len(above_d1_bb)} 只（需警惕回调），"
            f"下轨外 {len(below_d1_bb)} 只（超卖观察），"
            f"MA 高位 {len(d1_ma_above)} 只"
        ),
        "evidence": [
            f"日线 BB 上轨外 {len(above_d1_bb)} 只（收盘突破布林带上轨）",
            f"日线 BB 下轨外 {len(below_d1_bb)} 只（收盘跌破布林带下轨）",
            f"日线 MA 高位信号 {len(d1_ma_above)} 只（D6/D7 状态）",
        ],
        "risk": (
            f"{len(above_d1_bb)} 只标的价格处于 BB 上轨外，追高风险显著"
            if len(above_d1_bb) > 50 else "边界位置分布正常"
        ),
    }


def _risk_opinion(stocks: list[dict], market: dict) -> dict:
    risks = []
    if market["extreme_adx"] >= 5:
        risks.append(f"全市场 {market['extreme_adx']} 只 D1 ADX≥70，极端动量可能衰竭")
    if market["bearish_div"] >= 10:
        risks.append(f"全市场 {market['bearish_div']} 只 ADX≥30 但 -DI > +DI，动量反转风险")
    if market["fake_breakout"] >= 5:
        risks.append(f"全市场 {market['fake_breakout']} 只 BB 上轨突破但 D1 ADX < W1 ADX，假突破警告")
    if market["mn1_weak_ef2"] >= 20:
        risks.append(f"{market['mn1_weak_ef2']} 只 EF≥2 但 MN1 未在 E/F 牛市，长周期保护不足")
    return {
        "agent": "风险 Agent", "role": "风险识别与反驳",
        "verdict": "有风险" if len(risks) >= 2 else ("观察" if risks else "安全"),
        "verdict_color": "red" if len(risks) >= 2 else ("yellow" if risks else "green"),
        "conclusion": f"发现 {len(risks)} 项风险信号" + (f"：{'；'.join(risks)}" if risks else "，系统运行正常"),
        "evidence": risks if risks else ["无极端风险信号"],
        "risk": "多重风险叠加，建议降低仓位观察" if len(risks) >= 2 else (
            "个别风险信号需跟踪" if risks else "风险可控，可维持当前仓位"
        ),
    }


def _market_opinion(market: dict) -> dict:
    bull_pct = market["d1_bull_pct"]
    ef2_count = market["ef2_count"]
    phase = "强势多头" if bull_pct >= 55 and ef2_count >= 500 else (
        "温和偏多" if bull_pct >= 45 else "震荡整理"
    )
    return {
        "agent": "市场 Agent", "role": "市场环境总览",
        "verdict": phase,
        "verdict_color": "green" if "多头" in phase else "yellow",
        "conclusion": (
            f"全市场 {market['total_stocks']} 只，EF≥2 占比 "
            f"{ef2_count / market['total_stocks'] * 100:.0f}%，"
            f"D1 +DI > -DI 占比 {bull_pct}%，定性 {phase}"
        ),
        "evidence": [
            f"总股票数 {market['total_stocks']}，EF≥2 标的 {ef2_count} 只",
            f"D1 ADX 均值 {market['avg_d1_adx']}，W1 ADX 均值 {market['avg_w1_adx']}",
            f"日线动量偏多比例 {bull_pct}%，周线 {market['w1_bull_pct']}%",
            f"BB 上轨外 {market['d1_above_bb']} 只，下轨外 {market['d1_below_bb']} 只",
        ],
        "risk": "数据来源：State Cube（MN1/W1/D1 多周期全景），非实时盘中数据",
    }


def _per_stock_score(stock: dict, market: dict) -> dict:
    """对单只标的计算 6-Agent 评分的简化版，返回 label + score + 各维度得分。"""
    # 各维度得分 (0-1)，高于 0.5 为偏多
    scores = {}

    # 趋势维度：ef_count + 三周期 state_hex
    ef = stock.get("ef_count", 0)
    mn1 = str(stock.get("mn1_state_hex", ""))
    w1h = str(stock.get("w1_state_hex", ""))
    d1h = str(stock.get("d1_state_hex", ""))
    trend_score = 0.5
    if ef >= 3 and mn1 in ("E", "F"):
        trend_score = 0.85
    elif ef >= 3:
        trend_score = 0.75
    elif ef >= 2 and (mn1 in ("E", "F") or w1h in ("E", "F")):
        trend_score = 0.65
    elif ef >= 2:
        trend_score = 0.55
    elif ef <= 0:
        trend_score = 0.2
    scores["trend"] = round(trend_score, 2)

    # 动量维度：D1 ADX + DI 方向
    d1_adx = stock.get("d1_adx14", 0) or 0
    d1_plus = stock.get("d1_plus_di_14", 0) or 0
    d1_minus = stock.get("d1_minus_di_14", 0) or 0
    if d1_adx >= 40 and d1_plus > d1_minus:
        momentum_score = 0.85
    elif d1_adx >= 30 and d1_plus > d1_minus:
        momentum_score = 0.7
    elif d1_adx >= 25:
        momentum_score = 0.55
    elif d1_plus > d1_minus:
        momentum_score = 0.5
    else:
        momentum_score = 0.3
    scores["momentum"] = round(momentum_score, 2)

    # 波动率维度：BB 位置 + ATR
    d1_bb = str(stock.get("d1_bb20_position", ""))
    w1_bb = str(stock.get("w1_bb20_position", ""))
    atr_pct = (stock.get("d1_atr14", 0) or 0) / max(stock.get("d1_close", 1) or 1, 1) * 100
    if d1_bb == "above_upper" and w1_bb != "below_lower":
        vol_score = 0.65  # 突破但非极端
    elif d1_bb == "above_upper":
        vol_score = 0.5
    elif d1_bb == "below_lower":
        vol_score = 0.25
    elif atr_pct > 8:
        vol_score = 0.4
    else:
        vol_score = 0.55
    scores["volatility"] = round(vol_score, 2)

    # 边界维度：MA 状态 + BB 边界
    d1_ma = str(stock.get("d1_ma_state", ""))
    w1_ma = str(stock.get("w1_ma_state", ""))
    if "D6" in d1_ma or "D7" in d1_ma:
        boundary_score = 0.65
    elif d1_bb == "above_upper":
        boundary_score = 0.55
    elif d1_bb == "below_lower":
        boundary_score = 0.25
    elif "D4" in d1_ma or "D5" in d1_ma:
        boundary_score = 0.5
    else:
        boundary_score = 0.4
    scores["boundary"] = round(boundary_score, 2)

    # 风险维度：极端值 + 背离信号
    risk_deductions = 0.0
    if d1_adx >= 70:
        risk_deductions += 0.2  # 极端动量
    if d1_adx >= 30 and d1_minus > d1_plus:
        risk_deductions += 0.15  # 动量反转
    if d1_bb == "above_upper" and d1_adx < (stock.get("w1_adx14", 0) or 0):
        risk_deductions += 0.15  # 假突破
    if mn1 not in ("E", "F") and ef >= 2:
        risk_deductions += 0.1  # 长周期保护不足
    risk_score = max(0.1, 0.7 - risk_deductions)
    scores["risk"] = round(risk_score, 2)

    # 市场相对维度
    market_score = 0.5
    if d1_adx > market.get("avg_d1_adx", 20) and d1_plus > d1_minus:
        market_score = 0.65
    elif d1_adx > market.get("avg_d1_adx", 20):
        market_score = 0.55
    elif d1_plus < d1_minus:
        market_score = 0.35
    scores["market_relative"] = round(market_score, 2)

    # 复合加权评分（权重参照 Router 基础权重）
    composite = (
        scores["trend"] * 0.20 +
        scores["momentum"] * 0.18 +
        scores["volatility"] * 0.15 +
        scores["boundary"] * 0.12 +
        scores["risk"] * 0.20 +
        scores["market_relative"] * 0.15
    )

    if composite >= 0.7:
        label = "observe"
        color = "green"
        verdict = "偏多"
    elif composite >= 0.4:
        label = "watch"
        color = "yellow"
        verdict = "中性"
    else:
        label = "reject"
        color = "red"
        verdict = "防御"

    return {
        "stock_code": stock["stock_code"],
        "composite_score": round(composite, 2),
        "label": label,
        "color": color,
        "verdict": verdict,
        "dimension_scores": scores,
        "key_states": {
            "ef_count": ef,
            "mn1_state": mn1,
            "w1_state": w1h,
            "d1_state": d1h,
            "d1_adx": round(d1_adx, 1),
            "d1_plus_di": round(d1_plus, 1),
            "d1_minus_di": round(d1_minus, 1),
            "d1_bb": d1_bb,
            "w1_bb": w1_bb,
            "d1_ma": d1_ma,
            "atr_pct": round(atr_pct, 1),
        },
        "bullish_signals": sum(1 for v in scores.values() if v >= 0.6),
        "bearish_signals": sum(1 for v in scores.values() if v <= 0.35),
    }


def main() -> dict:
    latest_date = str(date.today())
    con = duckdb.connect(str(STATE_CUBE), read_only=True)
    try:
        actual = con.execute(
            "SELECT MAX(state_date) FROM state_cube WHERE state_date <= CURRENT_DATE"
        ).fetchone()[0]
        if actual:
            latest_date = str(actual)
    finally:
        con.close()

    market = _market_aggregates(latest_date)
    top_stocks = _query_cube(
        latest_date, where="ef_count >= 2 AND d1_close > 5", limit=50
    )

    opinions = [
        _market_opinion(market),
        _trend_opinion(top_stocks, market),
        _momentum_opinion(top_stocks, market),
        _volatility_opinion(top_stocks, market),
        _boundary_opinion(top_stocks, market),
        _risk_opinion(top_stocks, market),
    ]

    # Per-stock decision records
    per_stock_records = [_per_stock_score(s, market) for s in top_stocks]
    per_stock_records.sort(key=lambda r: r["composite_score"], reverse=True)

    result = {
        "generated_at": date.today().isoformat(),
        "state_date": latest_date,
        "cube_stocks": market["total_stocks"],
        "market_summary": market,
        "sample_stocks": len(top_stocks),
        "opinions": opinions,
        "per_stock_records": per_stock_records,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {OUTPUT} — {len(opinions)} agents, {len(per_stock_records)} per-stock records, state_date={latest_date}")
    return result


if __name__ == "__main__":
    main()
