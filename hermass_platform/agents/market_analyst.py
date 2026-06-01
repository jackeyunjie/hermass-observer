from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

from .base_agent import AgentContext, AgentResult, find_foundation_db

ROOT = Path(__file__).resolve().parents[2]


def analyze_market_environment(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="market_analyst",
        agent_name="市场环境分析师",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="market_analyst",
                agent_name="市场环境分析师",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    result = AgentResult(
        agent_id="market_analyst",
        agent_name="市场环境分析师",
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)

        latest_date_row = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()
        actual_date = str(latest_date_row[0]) if latest_date_row and latest_date_row[0] else ""

        base_row = con.execute(f"""
            SELECT
                COUNT(*) AS total_stocks,
                COUNT(DISTINCT stock_code) AS stock_count,
                SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END) AS ef2_count,
                ROUND(100.0 * SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0), 2) AS ef2_pct,
                ROUND(AVG(CASE WHEN mn1_state_score > 0 THEN mn1_state_score END), 2) AS avg_mn1_pos,
                ROUND(AVG(CASE WHEN w1_state_score > 0 THEN w1_state_score END), 2) AS avg_w1_pos,
                ROUND(AVG(CASE WHEN d1_state_score > 0 THEN d1_state_score END), 2) AS avg_d1_pos
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
        """).fetchone()

        ef_dist_row = con.execute(f"""
            SELECT ef_count, COUNT(*) AS cnt
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
            GROUP BY ef_count ORDER BY ef_count
        """).fetchall()

        sr_row = con.execute(f"""
            SELECT
                ROUND(100.0 * SUM(CASE WHEN d1_sr_ready = true THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0), 2) AS d1_sr_ready_pct,
                ROUND(100.0 * SUM(CASE WHEN w1_sr_ready = true THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0), 2) AS w1_sr_ready_pct,
                ROUND(100.0 * SUM(CASE WHEN mn1_sr_ready = true THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0), 2) AS mn1_sr_ready_pct
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
        """).fetchone()

        con.close()

        ef_dist = {f"ef{r[0]}": r[1] for r in ef_dist_row}

        data = {
            "date": actual_date,
            "total_stocks": base_row[0] if base_row else 0,
            "stock_count": base_row[1] if base_row else 0,
            "ef2_count": base_row[2] if base_row else 0,
            "ef2_pct": base_row[3] if base_row else 0.0,
            "ef_distribution": ef_dist,
            "sr_readiness": {
                "d1_pct": sr_row[0] if sr_row else 0.0,
                "w1_pct": sr_row[1] if sr_row else 0.0,
                "mn1_pct": sr_row[2] if sr_row else 0.0,
            },
            "avg_state_score": {
                "mn1": base_row[4] if base_row and base_row[4] else 0.0,
                "w1": base_row[5] if base_row and base_row[5] else 0.0,
                "d1": base_row[6] if base_row and base_row[6] else 0.0,
            },
        }

        ef2 = data["ef2_count"]
        ef2_pct = data["ef2_pct"]
        avg_d1 = data["avg_state_score"]["d1"]

        if ef2_pct > 20 and avg_d1 > 5.0:
            environment_label = "强趋势市场"
        elif ef2_pct > 10:
            environment_label = "趋势行进"
        elif ef2_pct > 5:
            environment_label = "震荡偏强"
        else:
            environment_label = "收缩/弱趋势"

        summary = (
            f"市场环境：{environment_label}。"
            f"全市场 {data['stock_count']} 只股票，"
            f"E/F≥2 共 {ef2} 只（占比 {ef2_pct}%）。"
            f"日均线 State 评分 {avg_d1} 分。"
        )

        result.data = data
        result.summary = summary

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()


def analyze_industry_heat(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    sw_l1_name: str = "",
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="market_analyst",
        agent_name="市场环境分析师",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="market_analyst",
                agent_name="市场环境分析师",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    result = AgentResult(
        agent_id="market_analyst",
        agent_name="市场环境分析师",
        status="ok",
    )

    try:
        industry_db = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
        industry_map = {}
        if industry_db.exists():
            icon = duckdb.connect(str(industry_db), read_only=True)
            map_rows = icon.execute("""
                SELECT stock_code, sw_l1
                FROM ifind_industry_chain_profile
                WHERE sw_l1 IS NOT NULL AND sw_l1 != ''
            """).fetchall()
            industry_map = {r[0]: r[1] for r in map_rows}
            icon.close()

        if sw_l1_name and industry_map:
            codes = [c for c, ind in industry_map.items() if ind == sw_l1_name]
        else:
            codes = list(industry_map.keys())

        if not codes:
            result.data = {
                "sw_l1": sw_l1_name,
                "total_in_industry": 0,
                "ef_summary": {},
            }
            result.summary = f"行业 '{sw_l1_name}' 无数据"
            return result.to_dict()

        code_str = "('" + "', '".join(codes[:5000]) + "')"

        con = duckdb.connect(foundation_db, read_only=True)
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END) AS ef2,
                ROUND(100.0 * SUM(CASE WHEN ef_count >= 2 THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0), 2) AS ef2_pct
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
              AND stock_code IN {code_str}
        """).fetchone()
        con.close()

        result.data = {
            "sw_l1": sw_l1_name or "全行业",
            "total_in_industry": row[0] if row else 0,
            "ef2_count": row[1] if row else 0,
            "ef2_pct": row[2] if row else 0.0,
        }

        if row and row[0] and row[0] > 0:
            pct = row[2]
            name = sw_l1_name or "全市场"
            result.summary = f"行业'{name}': {row[0]} 只股票, E/F≥2 占比 {pct}%"
        else:
            result.summary = f"行业'{sw_l1_name}' 本日无数据"

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()
