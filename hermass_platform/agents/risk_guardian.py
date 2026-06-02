from pathlib import Path
from typing import Optional

import duckdb

from hermass_platform.red_lines import (
    enforce_max_position,
    flag_data_anomaly,
    is_kill_switch_active,
)

from .base_agent import AgentContext, AgentResult, find_foundation_db

ROOT = Path(__file__).resolve().parents[2]

# ── 红线 4：不可绕过的仓位上限 ────────────────────────────────
MAX_POSITION_PCT = 0.25  # 单只股票最大 25%
MAX_INDUSTRY_PCT = 0.40  # 单行业最大 40%


def assess_portfolio_risk(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    stock_codes: Optional[list[str]] = None,
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="risk_guardian",
        agent_name="风控守门人",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="risk_guardian",
                agent_name="风控守门人",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    result = AgentResult(
        agent_id="risk_guardian",
        agent_name="风控守门人",
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)

        code_filter = ""
        if stock_codes and len(stock_codes) > 0:
            code_str = "('" + "', '".join(stock_codes) + "')"
            code_filter = f"AND s.stock_code IN {code_str}"

        latest_date_row = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()
        actual_date = str(latest_date_row[0]) if latest_date_row and latest_date_row[0] else ""

        risk_rows = con.execute(f"""
            SELECT
                s.stock_code,
                s.d1_close,
                s.ef_count,
                s.d1_state_hex,
                s.w1_state_hex,
                s.mn1_state_hex,
                s.d1_sr_support,
                s.d1_sr_resistance,
                s.d1_volatility,
                s.d1_atr_ratio_pct,
                s.d1_sr_ready,
                s.d1_adx14
            FROM d1_perspective_state s
            WHERE s.state_date = CAST('{actual_date}' AS DATE)
              {code_filter}
            ORDER BY s.ef_count, s.stock_code
            LIMIT 200
        """).fetchall()

        holdings = []
        risk_flags = []

        for row in risk_rows:
            stock_code = row[0]
            d1_close = row[1]
            ef_count = row[2]
            d1_hex = row[3]
            w1_hex = row[4]
            mn1_hex = row[5]
            d1_sr_support = row[6]
            d1_sr_resistance = row[7]
            d1_vol = row[8]
            atr_pct = row[9]
            sr_ready = row[10]
            adx = row[11]

            flags = []

            if ef_count == 0 and d1_hex in ("E", "F"):
                flags.append("D1 高位无大周期支撑，趋势延续性存疑")
            if ef_count <= 1:
                flags.append("仅 D1 周期独立，缺乏多周期共振")
            if isinstance(d1_vol, str) and "expand" in d1_vol.lower():
                flags.append("D1 波动率扩张，风险增大")
            if isinstance(atr_pct, (int, float)) and atr_pct > 5.0:
                flags.append(f"高波动个股 (ATR%={atr_pct:.1f}%)")
            if isinstance(adx, (int, float)) and adx < 15:
                flags.append("ADX 低迷，缺乏趋势动能")
            if not sr_ready:
                flags.append("SR 关键位未就绪，止损参考不可靠")

            holdings.append(
                {
                    "stock_code": stock_code,
                    "d1_close": d1_close,
                    "ef_count": ef_count,
                    "d1_state_hex": d1_hex,
                    "w1_state_hex": w1_hex,
                    "mn1_state_hex": mn1_hex,
                    "d1_sr_support": d1_sr_support,
                    "d1_sr_resistance": d1_sr_resistance,
                    "atr_ratio_pct": atr_pct,
                    "adx14": adx,
                    "risk_flags": flags,
                    "risk_level": "高" if len(flags) >= 2 else ("中" if len(flags) >= 1 else "低"),
                }
            )
            risk_flags.extend(flags)

        ef_dist = {}
        for h in holdings:
            key = f"ef{h['ef_count']}"
            ef_dist[key] = ef_dist.get(key, 0) + 1

        high_risk = sum(1 for h in holdings if h["risk_level"] == "高")
        med_risk = sum(1 for h in holdings if h["risk_level"] == "中")

        # ── 红线 4：仓位上限强制检查 ────────────────────────────
        position_checks = []
        for h in holdings:
            # 对每只持仓股进行仓位上限检查
            # 如果调用方传入了建议仓位，在此处强制截断
            check = enforce_max_position(
                stock_code=h["stock_code"],
                proposed_weight=1.0 / max(len(holdings), 1),  # 等权默认
                max_position_pct=MAX_POSITION_PCT,
                agent_id="risk_guardian",
            )
            h["position_cap"] = check["capped_weight"]
            h["position_allowed"] = check["allowed"]
            position_checks.append(check)

        # ── 红线 3：数据异常检测 ─────────────────────────────────
        anomaly_flags = []
        for h in holdings:
            if h.get("atr_ratio_pct") is not None and h["atr_ratio_pct"] > 20.0:
                anomaly = flag_data_anomaly(
                    agent_id="risk_guardian",
                    anomaly_type="outlier_atr_ratio",
                    stock_code=h["stock_code"],
                    details={"atr_ratio_pct": h["atr_ratio_pct"]},
                )
                anomaly_flags.append(anomaly)

        con.close()

        result.data = {
            "date": actual_date,
            "total_holdings": len(holdings),
            "holdings": holdings,
            "ef_distribution": ef_dist,
            "risk_summary": {
                "high_risk_count": high_risk,
                "medium_risk_count": med_risk,
                "low_risk_count": len(holdings) - high_risk - med_risk,
            },
            "total_risk_flags": len(risk_flags),
            "position_cap_enforced": any(not c["allowed"] for c in position_checks),
            "position_checks": position_checks,
            "max_position_pct": MAX_POSITION_PCT,
            "max_industry_pct": MAX_INDUSTRY_PCT,
            "data_anomalies": anomaly_flags,
            "kill_switch_active": is_kill_switch_active(),
        }

        if len(holdings) == 0:
            result.summary = "当前无持仓数据"
        else:
            result.summary = (
                f"持仓风险评估：共 {len(holdings)} 只，"
                f"高风险 {high_risk} 只，中风险 {med_risk} 只，"
                f"共触发 {len(risk_flags)} 个风险标记。"
            )

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()


def get_stop_loss_reference(
    user_id: str,
    stock_code: str,
    target_date: str = "",
    foundation_db: str = "",
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="risk_guardian",
        agent_name="风控守门人",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="risk_guardian",
                agent_name="风控守门人",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    result = AgentResult(
        agent_id="risk_guardian",
        agent_name="风控守门人",
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)
        row = con.execute(f"""
            SELECT
                d1_close,
                d1_sr_support,
                d1_sr_resistance,
                d1_atr_ratio_pct,
                d1_sr_ready,
                w1_sr_support,
                w1_sr_resistance,
                mn1_sr_support,
                mn1_sr_resistance,
                ef_count,
                d1_state_hex,
                w1_state_hex,
                mn1_state_hex
            FROM d1_perspective_state
            WHERE stock_code = '{stock_code}'
              AND state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
            LIMIT 1
        """).fetchone()
        con.close()

        if row is None:
            result.status = "error"
            result.errors.append(f"股票 {stock_code} 无数据")
            return result.to_dict()

        d1_close = row[0]
        d1_support = row[1]
        d1_resistance = row[2]
        atr_pct = row[3]
        sr_ready = row[4]

        stop_refs = []
        if sr_ready and d1_support and d1_support > 0:
            stop_refs.append(
                {
                    "method": "SR 支撑止损",
                    "reference_price": round(d1_support * 0.97, 2),
                    "description": f"D1 支撑位 {d1_support} 下方 3% 缓冲",
                }
            )
        if isinstance(atr_pct, (int, float)) and atr_pct > 0 and isinstance(d1_close, (int, float)):
            atr_value = d1_close * atr_pct / 100.0
            stop_refs.append(
                {
                    "method": "ATR 止损",
                    "reference_price": round(d1_close - atr_value * 2.0, 2),
                    "description": f"2×ATR({atr_value:.2f}) 止损",
                }
            )

        result.data = {
            "stock_code": stock_code,
            "d1_close": d1_close,
            "d1_sr_support": d1_support,
            "d1_sr_resistance": d1_resistance,
            "atr_ratio_pct": atr_pct,
            "sr_ready": sr_ready,
            "ef_count": row[9],
            "d1_state_hex": row[10],
            "w1_state_hex": row[11],
            "mn1_state_hex": row[12],
            "stop_loss_references": stop_refs,
        }

        if stop_refs:
            refs_text = "；".join(f"{r['method']}: {r['reference_price']}" for r in stop_refs)
            result.summary = f"{stock_code} 止损参考：{refs_text}"
        else:
            result.summary = f"{stock_code} 当前 SR 未就绪，无可靠止损参考"

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()
