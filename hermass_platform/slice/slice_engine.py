import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb

from .data_contract import compute_slice_checksum, compute_cache_key, validate_slice_result

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "outputs" / "slice_cache"

DEFAULT_LIMIT = 5000


def find_latest_foundation_db(date_str: str | None = None) -> Optional[Path]:
    candidates = sorted(
        ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"),
        reverse=True,
    )
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            if date_str:
                con = duckdb.connect(str(c), read_only=True)
                latest = con.execute(
                    "SELECT MAX(state_date) FROM d1_perspective_state"
                ).fetchone()[0]
                con.close()
                if latest and str(latest) >= date_str:
                    return c
            else:
                return c
    return None


def _read_cache(cache_key: str, today: str) -> Optional[dict]:
    path = CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_date = data.get("source", {}).get("cache_date", "")
        if cached_date == today:
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _write_cache(cache_key: str, result: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{cache_key}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _build_envelope(
    slice_type: str,
    params: dict,
    data: list,
    summary: dict,
    foundation_db: str,
    cache_date: str,
    signal_db: str | None = None,
) -> dict:
    checksum = compute_slice_checksum(data)
    return {
        "slice_type": slice_type,
        "slice_id": f"{slice_type}_{params.get('user_id', params.get('strategy_id', params.get('date', 'unknown')))}_{cache_date}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract_version": "1.0.0",
        "source": {
            "foundation_db": foundation_db,
            "signal_db": signal_db or "",
            "cache_date": cache_date,
        },
        "params": params,
        "data": data,
        "summary": summary,
        "integrity": {
            "checksum": checksum,
            "row_count": len(data),
        },
    }


def slice_user(
    foundation_db: str,
    user_id: str,
    target_date: str,
    stock_codes: Optional[list[str]] = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    from .user_slice import query_user_slice
    return query_user_slice(foundation_db, user_id, target_date, stock_codes, offset, limit)


def slice_strategy(
    foundation_db: str,
    signal_db: str,
    strategy_id: str,
    target_date: str,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    from .strategy_slice import query_strategy_slice
    return query_strategy_slice(foundation_db, signal_db, strategy_id, target_date, offset, limit)


def slice_time(
    foundation_db: str,
    target_date: str,
    lookback_days: int = 20,
    stock_codes: Optional[list[str]] = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    from .time_slice import query_time_slice
    return query_time_slice(foundation_db, target_date, lookback_days, stock_codes, offset, limit)


def slice(
    foundation_db: Path | str | None = None,
    slice_type: str = "user",
    params: dict | None = None,
    bypass_cache: bool = False,
    validate: bool = True,
) -> dict:
    if params is None:
        params = {}

    target_date = params.get("date")
    if not target_date:
        today = date.today().isoformat()
        target_date = today
        params = {**params, "date": today}

    if foundation_db is None:
        db_path = find_latest_foundation_db(target_date)
    else:
        db_path = Path(foundation_db)
    if db_path is None or not db_path.exists():
        raise FileNotFoundError(f"無可用 Foundation DB for date={target_date}")
    db_str = str(db_path)

    cache_date = target_date.replace("-", "")
    cache_key = compute_cache_key(slice_type, params, cache_date)

    if not bypass_cache:
        cached = _read_cache(cache_key, cache_date)
        if cached is not None:
            return cached

    signal_db = params.get("signal_db", "")
    if slice_type == "user":
        result = slice_user(
            db_str,
            params.get("user_id", "unknown"),
            target_date,
            params.get("stock_codes"),
            params.get("offset", 0),
            params.get("limit", DEFAULT_LIMIT),
        )
    elif slice_type == "strategy":
        result = slice_strategy(
            db_str,
            signal_db,
            params.get("strategy_id", "unknown"),
            target_date,
            params.get("offset", 0),
            params.get("limit", DEFAULT_LIMIT),
        )
    elif slice_type == "time":
        result = slice_time(
            db_str,
            target_date,
            params.get("lookback_days", 20),
            params.get("stock_codes"),
            params.get("offset", 0),
            params.get("limit", DEFAULT_LIMIT),
        )
    elif slice_type == "industry":
        from .industry_slice import query_industry_slice
        result = query_industry_slice(
            db_str,
            params.get("sw_l1", ""),
            target_date,
            params.get("offset", 0),
            params.get("limit", DEFAULT_LIMIT),
        )
    elif slice_type == "cognitive":
        from .cognitive_slice import query_cognitive_slice
        result = query_cognitive_slice(
            db_str,
            params.get("user_id", "unknown"),
            target_date,
            params.get("offset", 0),
            params.get("limit", DEFAULT_LIMIT),
        )
    else:
        raise ValueError(f"無效切片類型: {slice_type}")

    if validate:
        vr = validate_slice_result(result)
        if not vr.valid:
            violations = [(v.field, v.message) for v in vr.violations]
            raise ValueError(f"切片輸出校驗失敗: {violations}")

    _write_cache(cache_key, result)
    return result
