from datetime import datetime, timezone, timedelta

import duckdb

from .data_contract import compute_slice_checksum


def query_time_slice(
    foundation_db: str,
    target_date: str,
    lookback_days: int = 20,
    stock_codes: list[str] | None = None,
    offset: int = 0,
    limit: int = 5000,
) -> dict:
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    start_date = (dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    if stock_codes:
        code_list = "', '".join(stock_codes)
        code_filter = f"AND s.stock_code IN ('{code_list}')"
    else:
        code_filter = ""

    con = duckdb.connect(foundation_db, read_only=True)
    try:
        total = con.execute(f"""
            SELECT COUNT(DISTINCT stock_code)
            FROM d1_perspective_state s
            WHERE s.state_date BETWEEN DATE '{start_date}' AND DATE '{target_date}'
              {code_filter}
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
                s.mn1_trend,
                s.mn1_sr_ready,
                s.w1_sr_ready,
                s.d1_sr_ready,
                prev.ef_count AS prev_ef_count
            FROM d1_perspective_state s
            LEFT JOIN d1_perspective_state prev
              ON prev.stock_code = s.stock_code
             AND prev.state_date = s.state_date - INTERVAL 1 DAY
            WHERE s.state_date BETWEEN DATE '{start_date}' AND DATE '{target_date}'
              {code_filter}
            ORDER BY s.stock_code, s.state_date DESC
            LIMIT {limit} OFFSET {offset}
        """).fetchall()

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
                "mn1_trend": row[10] or "",
                "mn1_sr_ready": bool(row[11]) if row[11] is not None else False,
                "w1_sr_ready": bool(row[12]) if row[12] is not None else False,
                "d1_sr_ready": bool(row[13]) if row[13] is not None else False,
                "prev_ef_count": row[14] if row[14] is not None else -1,
            }
            data.append(entry)
    finally:
        con.close()

    ef_dist = {"ef0": 0, "ef1": 0, "ef2": 0, "ef3": 0}
    latest_rows = {}
    for row in data:
        code = row["stock_code"]
        if code not in latest_rows:
            latest_rows[code] = row
    for row in latest_rows.values():
        key = f"ef{row['ef_count']}"
        if key in ef_dist:
            ef_dist[key] += 1

    return {
        "slice_type": "time",
        "slice_id": f"time_{target_date.replace('-', '')}_lb{lookback_days}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "cache_date": target_date.replace("-", ""),
        },
        "params": {
            "date": target_date,
            "lookback_days": lookback_days,
            "offset": offset,
            "limit": limit,
        },
        "data": data,
        "summary": {
            "row_count": min(len(data), limit),
            "total_unique_stocks": total,
            "date_range": {"from": start_date, "to": target_date},
            "ef_distribution": ef_dist,
            "truncated": total > offset + limit,
        },
        "integrity": {
            "checksum": compute_slice_checksum(data),
            "row_count": len(data),
        },
    }
