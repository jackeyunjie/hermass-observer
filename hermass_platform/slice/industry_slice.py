from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .data_contract import compute_slice_checksum

ROOT = Path(__file__).resolve().parents[2]
FUNDAMENTAL_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"


def _load_industry_map() -> dict[str, str]:
    if not FUNDAMENTAL_DB.exists():
        return {}
    con = duckdb.connect(str(FUNDAMENTAL_DB), read_only=True)
    try:
        rows = con.execute("""
            SELECT stock_code, sw_l1
            FROM ifind_industry_chain_profile
            WHERE sw_l1 IS NOT NULL AND sw_l1 != ''
        """).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        con.close()


def query_industry_slice(
    foundation_db: str,
    sw_l1_name: str,
    target_date: str,
    offset: int = 0,
    limit: int = 5000,
) -> dict:
    industry_map = _load_industry_map()

    if industry_map:
        codes_in_industry = [c for c, ind in industry_map.items() if ind == sw_l1_name]
        if not codes_in_industry:
            return {
                "slice_type": "industry",
                "slice_id": f"industry_{sw_l1_name}_{target_date.replace('-', '')}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "contract_version": "1.0.0",
                "source": {
                    "foundation_db": foundation_db,
                    "industry_db": str(FUNDAMENTAL_DB),
                    "cache_date": target_date.replace("-", ""),
                },
                "params": {
                    "sw_l1": sw_l1_name,
                    "date": target_date,
                    "offset": offset,
                    "limit": limit,
                },
                "data": [],
                "summary": {
                    "row_count": 0,
                    "total_in_industry": 0,
                    "total_with_state": 0,
                    "ef_distribution": {"ef0": 0, "ef1": 0, "ef2": 0, "ef3": 0},
                    "truncated": False,
                },
                "integrity": {
                    "checksum": compute_slice_checksum([]),
                    "row_count": 0,
                },
            }
        code_filter = "('" + "', '".join(codes_in_industry) + "')"
    else:
        code_filter = "('')"

    con = duckdb.connect(foundation_db, read_only=True)
    try:
        total_in_industry = con.execute(f"""
            SELECT COUNT(DISTINCT stock_code)
            FROM d1_perspective_state
            WHERE state_date = DATE '{target_date}'
              AND stock_code IN {code_filter}
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
                s.d1_sr_ready
            FROM d1_perspective_state s
            WHERE s.state_date = DATE '{target_date}'
              AND s.stock_code IN {code_filter}
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
                    "sw_l1": sw_l1_name,
                    "mn1_sr_ready": bool(row[11]) if row[11] is not None else False,
                    "w1_sr_ready": bool(row[12]) if row[12] is not None else False,
                    "d1_sr_ready": bool(row[13]) if row[13] is not None else False,
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
        "slice_type": "industry",
        "slice_id": f"industry_{sw_l1_name}_{target_date.replace('-', '')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "industry_db": str(FUNDAMENTAL_DB),
            "cache_date": target_date.replace("-", ""),
        },
        "params": {
            "sw_l1": sw_l1_name,
            "date": target_date,
            "offset": offset,
            "limit": limit,
        },
        "data": data,
        "summary": {
            "row_count": min(len(data), limit),
            "total_in_industry": total_in_industry,
            "total_with_state": len(data),
            "ef_distribution": ef_dist,
            "truncated": total_in_industry > offset + limit,
        },
        "integrity": {
            "checksum": compute_slice_checksum(data),
            "row_count": len(data),
        },
    }


def list_industries() -> list[str]:
    industry_map = _load_industry_map()
    return sorted(set(industry_map.values()))


def detect_sector_resonance(
    foundation_db: str,
    target_date: str = "",
    min_stocks: int = 3,
) -> list[dict]:
    industry_map = _load_industry_map()
    if not industry_map:
        return []

    con = duckdb.connect(foundation_db, read_only=True)
    try:
        latest_date = target_date
        if not latest_date:
            r = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()
            latest_date = str(r[0]) if r and r[0] else ""

        prev_date = con.execute(
            "SELECT MAX(state_date) FROM d1_perspective_state WHERE state_date < CAST(? AS DATE)",
            [latest_date],
        ).fetchone()[0]

        if not prev_date:
            return []

        today_ef = con.execute(f"""
            SELECT stock_code, ef_count
            FROM d1_perspective_state
            WHERE state_date = CAST('{latest_date}' AS DATE)
              AND ef_count >= 2
        """).fetchall()
        today_set = {r[0]: r[1] for r in today_ef}

        prev_ef = con.execute(f"""
            SELECT stock_code, ef_count
            FROM d1_perspective_state
            WHERE state_date = CAST('{prev_date}' AS DATE)
        """).fetchall()
        prev_dict = {r[0]: r[1] for r in prev_ef}

        resonance_signals: dict[str, list[dict]] = {}
        for code, ef in today_set.items():
            industry = industry_map.get(code, "")
            if not industry:
                continue
            prev = prev_dict.get(code, -1)
            if prev < 2 and ef >= 2:
                if industry not in resonance_signals:
                    resonance_signals[industry] = []
                resonance_signals[industry].append(
                    {
                        "stock_code": code,
                        "ef_count": ef,
                        "prev_ef_count": prev,
                    }
                )

        results = []
        for industry, stocks in resonance_signals.items():
            if len(stocks) >= min_stocks:
                results.append(
                    {
                        "sw_l1": industry,
                        "resonance_count": len(stocks),
                        "date": latest_date,
                        "prev_date": str(prev_date),
                        "signals": stocks,
                        "confidence": "高" if len(stocks) >= 5 else ("中" if len(stocks) >= 4 else "低"),
                    }
                )

        results.sort(key=lambda x: -x["resonance_count"])
        return results
    finally:
        con.close()
