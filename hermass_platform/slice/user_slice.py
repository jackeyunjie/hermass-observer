from datetime import datetime, timezone

import duckdb

from .data_contract import compute_slice_checksum


def query_user_slice(
    foundation_db: str,
    user_id: str,
    target_date: str,
    stock_codes: list[str] | None = None,
    offset: int = 0,
    limit: int = 5000,
) -> dict:
    if stock_codes:
        code_list = "', '".join(stock_codes)
        code_filter = f"AND s.stock_code IN ('{code_list}')"
    else:
        code_filter = ""

    con = duckdb.connect(foundation_db, read_only=True)
    try:
        total = con.execute(f"""
            SELECT COUNT(*)
            FROM d1_perspective_state s
            WHERE s.state_date = DATE '{target_date}'
              AND s.ef_count >= 2
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
                s.mn1_volatility,
                s.mn1_sr_ready,
                s.w1_sr_ready,
                s.d1_sr_ready
            FROM d1_perspective_state s
            WHERE s.state_date = DATE '{target_date}'
              {code_filter}
            ORDER BY s.ef_count DESC, s.stock_code
            LIMIT {limit} OFFSET {offset}
        """).fetchall()

        data = []
        for row in rows:
            data.append(
                {
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
                    "mn1_volatility": row[11] or "",
                    "mn1_sr_ready": bool(row[12]) if row[12] is not None else False,
                    "w1_sr_ready": bool(row[13]) if row[13] is not None else False,
                    "d1_sr_ready": bool(row[14]) if row[14] is not None else False,
                }
            )
    finally:
        con.close()

    ef_dist = {"ef0": 0, "ef1": 0, "ef2": 0, "ef3": 0}
    for row in data:
        key = f"ef{row['ef_count']}"
        if key in ef_dist:
            ef_dist[key] += 1

    return {
        "slice_type": "user",
        "slice_id": f"user_{user_id}_{target_date.replace('-', '')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "cache_date": target_date.replace("-", ""),
        },
        "params": {
            "user_id": user_id,
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
