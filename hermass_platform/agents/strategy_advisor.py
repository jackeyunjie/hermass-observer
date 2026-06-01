from pathlib import Path
from typing import Optional

import duckdb

from .base_agent import AgentContext, AgentResult, find_foundation_db, find_signal_db

ROOT = Path(__file__).resolve().parents[2]


def analyze_strategy_fit(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    signal_db: str = "",
    strategy_id: str = "",
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="strategy_advisor",
        agent_name="策略适配顾问",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
        signal_db=signal_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="strategy_advisor",
                agent_name="策略适配顾问",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    if not signal_db:
        sig_path = find_signal_db()
        if sig_path and sig_path.exists():
            signal_db = str(sig_path)

    result = AgentResult(
        agent_id="strategy_advisor",
        agent_name="策略适配顾问",
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)
        has_signal = False
        signal_path = ""

        if signal_db and Path(signal_db).exists():
            signal_path = signal_db
            try:
                con.execute(f"ATTACH '{signal_db.replace(chr(39), chr(39) + chr(39))}' AS sig (READ_ONLY)")
                exists = (
                    con.execute(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema='sig' AND table_name='strategy_signal_daily'"
                    ).fetchone()[0]
                    > 0
                )
                if exists:
                    has_signal = True
            except Exception:
                pass

        strategy_ids = []
        if has_signal:
            strat_rows = con.execute("SELECT DISTINCT strategy_id FROM sig.strategy_signal_daily").fetchall()
            strategy_ids = [r[0] for r in strat_rows]

        target_strategies = [strategy_id] if strategy_id and strategy_id in strategy_ids else strategy_ids

        strategy_stats = []
        if has_signal and target_strategies:
            latest_date = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]

            for sid in target_strategies:
                stat_row = con.execute(f"""
                    SELECT
                        COUNT(*) AS signal_count,
                        SUM(CASE WHEN s.ef_count >= 2 THEN 1 ELSE 0 END) AS ef2_signal_count,
                        ROUND(AVG(s.ef_count), 2) AS avg_ef,
                        ROUND(100.0 * SUM(CASE WHEN s.ef_count >= 2 THEN 1 ELSE 0 END)
                              / NULLIF(COUNT(*), 0), 2) AS ef2_pct
                    FROM d1_perspective_state s
                    INNER JOIN sig.strategy_signal_daily sig
                      ON sig.stock_code = s.stock_code
                     AND sig.signal_date = s.state_date::VARCHAR
                    WHERE s.state_date = CAST('{latest_date}' AS DATE)
                      AND sig.strategy_id = '{sid}'
                """).fetchone()

                fit_counts = con.execute(f"""
                    SELECT environment_fit, COUNT(*) AS cnt
                    FROM sig.strategy_signal_daily
                    WHERE signal_date = CAST('{latest_date}' AS VARCHAR)
                      AND strategy_id = '{sid}'
                    GROUP BY environment_fit
                    ORDER BY environment_fit
                """).fetchall()

                strategy_stats.append(
                    {
                        "strategy_id": sid,
                        "strategy_label": _strategy_label(sid),
                        "signal_count": stat_row[0] if stat_row else 0,
                        "ef2_signal_count": stat_row[1] if stat_row else 0,
                        "avg_ef_count": stat_row[2] if stat_row else 0.0,
                        "ef2_pct": stat_row[3] if stat_row else 0.0,
                        "fit_distribution": {r[0] or "未知": r[1] for r in fit_counts},
                    }
                )

        ef_overview = con.execute(f"""
            SELECT
                ef_count,
                COUNT(*) AS cnt,
                ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
            FROM d1_perspective_state
            WHERE state_date = (SELECT MAX(state_date) FROM d1_perspective_state)
            GROUP BY ef_count ORDER BY ef_count
        """).fetchall()

        con.close()

        ef_summary = {f"ef{r[0]}": {"count": r[1], "pct": r[2]} for r in ef_overview}

        best = None
        for s in strategy_stats:
            if best is None or s["ef2_pct"] > best["ef2_pct"]:
                best = s

        summary = ""
        if strategy_stats:
            lines = []
            for s in strategy_stats:
                lines.append(
                    f"{s['strategy_label']}: 信号 {s['signal_count']} 个, E/F≥2 占比 {s['ef2_pct']}%"
                )
            summary = "策略适配概览：\n" + "\n".join(lines)
            if best:
                summary += f"\n\n当前最适配策略：{best['strategy_label']}"
        else:
            summary = "无可用策略信号数据"

        result.data = {
            "date": str(ef_overview[0][0]) if ef_overview else target_date,
            "strategies": strategy_stats,
            "available_strategies": strategy_ids,
            "ef_market_overview": ef_summary,
            "best_fit_strategy": best["strategy_id"] if best else "",
        }
        result.summary = summary

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()


def explore_top_signals(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    signal_db: str = "",
    strategy_id: str = "",
    top_n: int = 20,
    session_id: str = "",
) -> dict:
    ctx = AgentContext(
        agent_id="strategy_advisor",
        agent_name="策略适配顾问",
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
        signal_db=signal_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id="strategy_advisor",
                agent_name="策略适配顾问",
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    if not signal_db:
        sig_path = find_signal_db()
        if sig_path and sig_path.exists():
            signal_db = str(sig_path)

    result = AgentResult(
        agent_id="strategy_advisor",
        agent_name="策略适配顾问",
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)
        has_signal = False

        if signal_db and Path(signal_db).exists():
            try:
                con.execute(f"ATTACH '{signal_db.replace(chr(39), chr(39) + chr(39))}' AS sig (READ_ONLY)")
                exists = (
                    con.execute(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema='sig' AND table_name='strategy_signal_daily'"
                    ).fetchone()[0]
                    > 0
                )
                if exists:
                    has_signal = True
            except Exception:
                pass

        signals = []
        if has_signal:
            latest_date = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()[0]
            date_str = str(latest_date)

            strat_filter = f"AND sig.strategy_id = '{strategy_id}'" if strategy_id else ""

            rows = con.execute(f"""
                SELECT
                    s.stock_code,
                    s.ef_count,
                    s.mn1_state_hex,
                    s.w1_state_hex,
                    s.d1_state_hex,
                    sig.signal_name,
                    sig.strategy_id,
                    sig.environment_fit,
                    sig.lifecycle_stage
                FROM d1_perspective_state s
                INNER JOIN sig.strategy_signal_daily sig
                  ON sig.stock_code = s.stock_code
                 AND sig.signal_date = s.state_date::VARCHAR
                WHERE s.state_date = CAST('{date_str}' AS DATE)
                  {strat_filter}
                ORDER BY s.ef_count DESC, s.d1_state_score DESC
                LIMIT {top_n}
            """).fetchall()

            for row in rows:
                signals.append(
                    {
                        "stock_code": row[0],
                        "ef_count": row[1],
                        "mn1_state_hex": row[2],
                        "w1_state_hex": row[3],
                        "d1_state_hex": row[4],
                        "signal_name": row[5] or "",
                        "strategy_id": row[6] or "",
                        "environment_fit": row[7] or "",
                        "lifecycle_stage": row[8] or "",
                    }
                )

        con.close()

        result.data = {
            "top_signals": signals,
            "total": len(signals),
        }

        if signals:
            top_ef3 = sum(1 for s in signals if s["ef_count"] == 3)
            result.summary = f"今日优质信号共 {len(signals)} 个，其中三周期共振（ef_count=3）{top_ef3} 个"
        else:
            result.summary = "今日无策略信号"

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))

    return result.to_dict()


def _strategy_label(strategy_id: str) -> str:
    labels = {
        "ma2560": "MA2560 策略",
        "vcp": "VCP 收缩突破策略",
        "bollinger_bandit": "布林强盗策略",
        "atr_chandelier": "ATR 吊灯策略",
    }
    return labels.get(strategy_id, strategy_id)
