from datetime import datetime, timezone

import duckdb

from .data_contract import compute_slice_checksum


def query_strategy_slice(
    foundation_db: str,
    signal_db: str,
    strategy_id: str,
    target_date: str,
    offset: int = 0,
    limit: int = 5000,
) -> dict:
    has_signal = False
    con = duckdb.connect(foundation_db, read_only=True)

    try:
        if signal_db:
            signal_path = signal_db
            sig_exists = True
        else:
            from pathlib import Path

            ROOT = Path(__file__).resolve().parents[2]
            candidates = sorted(
                ROOT.glob("outputs/strategy_signals/strategy_signals.duckdb"),
            )
            if candidates and candidates[0].exists():
                signal_path = str(candidates[0])
                sig_exists = True
            else:
                sig_exists = False

        if sig_exists and signal_path:
            con.execute(f"ATTACH '{signal_path.replace(chr(39), chr(39) + chr(39))}' AS sig (READ_ONLY)")
            has_signal = (
                con.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema='sig' AND table_name='strategy_signal_daily'"
                ).fetchone()[0]
                > 0
            )

        if has_signal:
            total = con.execute(f"""
                SELECT COUNT(*)
                FROM d1_perspective_state s
                INNER JOIN sig.strategy_signal_daily sig
                  ON sig.stock_code = s.stock_code
                 AND sig.signal_date = s.state_date
                WHERE s.state_date = DATE '{target_date}'
                  AND sig.strategy_id = '{strategy_id}'
            """).fetchone()[0]

            rows = con.execute(f"""
                SELECT
                    s.stock_code,
                    s.state_date::VARCHAR AS state_date,
                    s.d1_close,
                    s.mn1_state_hex,
                    s.w1_state_hex,
                    s.d1_state_hex,
                    s.mn1_state_score,
                    s.w1_state_score,
                    s.d1_state_score,
                    s.ef_count,
                    s.mn1_sr_ready,
                    s.w1_sr_ready,
                    s.d1_sr_ready,
                    sig.signal_name,
                    sig.environment_fit,
                    sig.lifecycle_stage
                FROM d1_perspective_state s
                INNER JOIN sig.strategy_signal_daily sig
                  ON sig.stock_code = s.stock_code
                 AND sig.signal_date = s.state_date
                WHERE s.state_date = DATE '{target_date}'
                  AND sig.strategy_id = '{strategy_id}'
                ORDER BY s.ef_count DESC, sig.environment_fit DESC
                LIMIT {limit} OFFSET {offset}
            """).fetchall()
        else:
            total = 0
            rows = []
    finally:
        con.close()

    data = []
    for row in rows:
        entry = {
            "stock_code": row[0],
            "state_date": row[1],
            "d1_close": row[2],
            "mn1_state_hex": row[3],
            "w1_state_hex": row[4],
            "d1_state_hex": row[5],
            "mn1_state_score": row[6],
            "w1_state_score": row[7],
            "d1_state_score": row[8],
            "ef_count": row[9],
            "mn1_sr_ready": bool(row[10]) if row[10] is not None else False,
            "w1_sr_ready": bool(row[11]) if row[11] is not None else False,
            "d1_sr_ready": bool(row[12]) if row[12] is not None else False,
        }
        if has_signal:
            entry["signal_name"] = row[13] or ""
            entry["environment_fit"] = row[14] or ""
            entry["lifecycle_stage"] = row[15] or ""
        data.append(entry)

    ef_dist = {"ef0": 0, "ef1": 0, "ef2": 0, "ef3": 0}
    for row in data:
        key = f"ef{row['ef_count']}"
        if key in ef_dist:
            ef_dist[key] += 1

    return {
        "slice_type": "strategy",
        "slice_id": f"strategy_{strategy_id}_{target_date.replace('-', '')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "signal_db": signal_db,
            "cache_date": target_date.replace("-", ""),
        },
        "params": {
            "strategy_id": strategy_id,
            "date": target_date,
            "offset": offset,
            "limit": limit,
        },
        "data": data,
        "summary": {
            "row_count": min(len(data), limit),
            "total_matching": total,
            "ef_distribution": ef_dist,
            "truncated": total > offset + limit,
        },
        "integrity": {
            "checksum": compute_slice_checksum(data),
            "row_count": len(data),
        },
    }
