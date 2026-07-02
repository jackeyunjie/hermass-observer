"""State Timeline Observer 查询服务。

为 /state-observer 页面和 /api/state-observer 提供只读长表查询。
长表真相模型：一只股票 × 一个交易日 = 一行。

数据源：
- outputs/p116_foundation_YYYYMMDD/p116_foundation.duckdb（主数据源）
- outputs/fundamental/fundamental_evidence.duckdb（股票名称、行业映射，可选）

本模块只读取 Foundation DB，不写入。当 fundamental DB 不可用时，
stock_name 与 industry_l1 会优雅降级为 NULL / '未分类'，不会导致查询失败。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

log = logging.getLogger("hermass.web.state_timeline_observer")

ROOT = Path(__file__).resolve().parents[2]

# 预计算表切换开关：默认关闭，通过环境变量 USE_STATE_TIMELINE_MATERIALIZED=1 开启
USE_STATE_TIMELINE_MATERIALIZED = os.environ.get("USE_STATE_TIMELINE_MATERIALIZED", "0") == "1"
STATE_TIMELINE_MATERIALIZED_DIR = ROOT / "outputs" / "state_timeline"

# 事件族定义（与 STATE_BASE_CONTRACT.md 保持一致）
# E/F：state_score ∈ {14, 15}（仅正值）
# A/B：state_magnitude ∈ {10, 11}（含正负方向）
# 0  ：state_magnitude = 0


def find_foundation_db() -> Path | None:
    """返回最新的 Foundation DB 路径。"""
    candidates = sorted(ROOT.glob("outputs/p116_foundation_*/p116_foundation.duckdb"), reverse=True)
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


def _canonical_stock_code(value: str) -> str:
    """把 6 位数字代码规范化为带后缀的代码。"""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        return value.upper()
    if digits.startswith(("6", "9")):
        return f"{digits}.SH"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _resolve_watchlist_codes(user_key: str) -> list[str]:
    """从 user_task_ledger.json 读取 active watch_command 任务，返回规范化股票代码列表。

    匿名或空 user_key 时返回空列表，避免跨用户泄露 watchlist。
    """
    if not user_key or user_key.lower() in ("", "anonymous", "__anonymous__"):
        return []

    try:
        from agently_adapter.tools.user_tasks import list_user_tasks
    except Exception as exc:
        log.warning("导入 user_tasks 失败: %s", exc)
        return []

    try:
        payload = list_user_tasks(
            user=user_key,
            status="active",
            task_type="watch_command",
            limit=500,
        )
    except Exception as exc:
        log.warning("读取 watchlist 任务失败: %s", exc)
        return []

    codes: list[str] = []
    for task in payload.get("tasks", []) or []:
        code = str(task.get("stock_code") or "").strip()
        if code:
            codes.append(_canonical_stock_code(code))
    # 去重并保留顺序
    seen: set[str] = set()
    unique: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique.append(code)
    return unique


def _parse_bool_param(value: Any) -> bool | None:
    """解析 query bool 参数。"""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return None


def _parse_date_param(value: Any) -> date | None:
    """解析日期参数。"""
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except Exception:
        pass
    try:
        return __import__("datetime").datetime.strptime(text, "%Y%m%d").date()
    except Exception:
        return None


def _resolve_date_range(
    con: duckdb.DuckDBPyConnection,
    date_from: date | None,
    date_to: date | None,
    days: int | None,
) -> tuple[date, date]:
    """把 days / date_from / date_to 统一为绝对日期区间。"""
    max_date_row = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()
    max_date = max_date_row[0] if max_date_row and max_date_row[0] else date.today()

    if date_from and date_to:
        # 允许用户写反，自动校正
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    if date_from:
        return date_from, max_date

    if date_to:
        effective_days = max(1, days or 20)
        return date_to - timedelta(days=effective_days - 1), date_to

    effective_days = max(1, days or 20)
    return max_date - timedelta(days=effective_days - 1), max_date


def _build_core_query(
    symbols: list[str] | None,
    symbol_set: str | None,
    date_from: date,
    date_to: date,
    filters: dict[str, Any],
    top50_codes: list[str] | None,
    watchlist_codes: list[str] | None,
    has_fundamental: bool,
) -> tuple[str, list[Any]]:
    """构建 State Timeline 长表查询 SQL 与参数。"""

    # 标的范围
    symbol_clause = "TRUE"
    params: list[Any] = []

    is_watchlist = symbol_set and symbol_set.lower() == "watchlist"

    effective_symbols: list[str] = []
    if symbols:
        effective_symbols = [_canonical_stock_code(s) for s in symbols if s.strip()]
    elif symbol_set and symbol_set.lower() == "top50" and top50_codes:
        effective_symbols = top50_codes
    elif is_watchlist:
        effective_symbols = watchlist_codes or []

    if is_watchlist and not effective_symbols:
        # watchlist 为空时，明确返回空结果，而不是退化成全市场
        symbol_clause = "FALSE"
    elif effective_symbols:
        placeholders = ", ".join(["?"] * len(effective_symbols))
        symbol_clause = f"s.stock_code IN ({placeholders})"
        params.extend(effective_symbols)

    # 时间范围
    params.extend([date_from, date_to])

    # 布尔过滤（应用在 derived CTE 之后）
    derived_where_parts: list[str] = []
    bool_fields = [
        "mn1_is_ef", "w1_is_ef", "d1_is_ef",
        "mn1_is_ab", "w1_is_ab", "d1_is_ab",
        "mn1_is_zero", "w1_is_zero", "d1_is_zero",
    ]
    for field in bool_fields:
        value = _parse_bool_param(filters.get(field))
        if value is not None:
            derived_where_parts.append(f"d.{field} = ?")
            params.append(value)

    # 交集模式过滤
    for pattern_field in ("ef_pattern_any", "ab_pattern_any", "zero_pattern_any"):
        value = filters.get(pattern_field)
        if not value:
            continue
        if isinstance(value, str):
            patterns = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, list):
            patterns = [str(p).strip() for p in value if str(p).strip()]
        else:
            patterns = []
        if not patterns:
            continue
        target = pattern_field.replace("_pattern_any", "_pattern")
        placeholders = ", ".join(["?"] * len(patterns))
        derived_where_parts.append(f"d.{target} IN ({placeholders})")
        params.extend(patterns)

    all_where_parts = list(derived_where_parts)

    # 行业过滤（只有在 fundamental DB 存在时才生效）
    industry = filters.get("industry_l1")
    if has_fundamental and industry:
        if isinstance(industry, str):
            industries = [i.strip() for i in industry.split(",") if i.strip()]
        elif isinstance(industry, list):
            industries = [str(i).strip() for i in industry if str(i).strip()]
        else:
            industries = []
        if industries:
            placeholders = ", ".join(["?"] * len(industries))
            all_where_parts.append(f"COALESCE(m.sw_l1, '未分类') IN ({placeholders})")
            params.extend(industries)

    where_sql = "WHERE " + " AND ".join(all_where_parts) if all_where_parts else ""

    # 根据 fundamental DB 是否存在，选择是否 JOIN 行业表
    if has_fundamental:
        select_meta = """
        m.stock_name,
        COALESCE(m.sw_l1, '未分类') AS industry_l1,
        """
        join_meta = """
        LEFT JOIN (
            SELECT stock_code, stock_name, sw_l1,
                   ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY as_of_date DESC) AS rn
            FROM fund.ifind_industry_chain_profile
        ) m ON d.stock_code = m.stock_code AND m.rn = 1
        """
    else:
        select_meta = """
        NULL::VARCHAR AS stock_name,
        '未分类'::VARCHAR AS industry_l1,
        """
        join_meta = ""

    sql = f"""
    WITH base AS (
        SELECT
            s.stock_code,
            s.state_date,
            s.d1_close AS close,
            db.volume AS volume,
            s.mn1_state_hex,
            s.w1_state_hex,
            s.d1_state_hex,
            s.mn1_state_score,
            s.w1_state_score,
            s.d1_state_score,
            s.mn1_state_magnitude,
            s.w1_state_magnitude,
            s.d1_state_magnitude
        FROM d1_perspective_state s
        LEFT JOIN daily_bars db
            ON s.stock_code = db.stock_code AND s.state_date = db.date
        WHERE {symbol_clause}
          AND s.state_date BETWEEN ? AND ?
    ),
    flags AS (
        SELECT
            *,
            (mn1_state_score IN (14, 15)) AS mn1_is_ef,
            (w1_state_score IN (14, 15)) AS w1_is_ef,
            (d1_state_score IN (14, 15)) AS d1_is_ef,
            (mn1_state_magnitude IN (10, 11)) AS mn1_is_ab,
            (w1_state_magnitude IN (10, 11)) AS w1_is_ab,
            (d1_state_magnitude IN (10, 11)) AS d1_is_ab,
            (mn1_state_magnitude = 0) AS mn1_is_zero,
            (w1_state_magnitude = 0) AS w1_is_zero,
            (d1_state_magnitude = 0) AS d1_is_zero
        FROM base
    ),
    derived AS (
        SELECT
            *,
            (CAST(mn1_is_ef AS INTEGER) + CAST(w1_is_ef AS INTEGER) + CAST(d1_is_ef AS INTEGER)) AS ef_count,
            (CAST(mn1_is_ab AS INTEGER) + CAST(w1_is_ab AS INTEGER) + CAST(d1_is_ab AS INTEGER)) AS ab_count,
            (CAST(mn1_is_zero AS INTEGER) + CAST(w1_is_zero AS INTEGER) + CAST(d1_is_zero AS INTEGER)) AS zero_count,
            CASE
                WHEN mn1_is_ef AND w1_is_ef AND d1_is_ef THEN 'MN1+W1+D1'
                WHEN mn1_is_ef AND w1_is_ef THEN 'MN1+W1'
                WHEN mn1_is_ef AND d1_is_ef THEN 'MN1+D1'
                WHEN w1_is_ef AND d1_is_ef THEN 'W1+D1'
                WHEN mn1_is_ef THEN 'MN1'
                WHEN w1_is_ef THEN 'W1'
                WHEN d1_is_ef THEN 'D1'
                ELSE '-'
            END AS ef_pattern,
            CASE
                WHEN mn1_is_ab AND w1_is_ab AND d1_is_ab THEN 'MN1+W1+D1'
                WHEN mn1_is_ab AND w1_is_ab THEN 'MN1+W1'
                WHEN mn1_is_ab AND d1_is_ab THEN 'MN1+D1'
                WHEN w1_is_ab AND d1_is_ab THEN 'W1+D1'
                WHEN mn1_is_ab THEN 'MN1'
                WHEN w1_is_ab THEN 'W1'
                WHEN d1_is_ab THEN 'D1'
                ELSE '-'
            END AS ab_pattern,
            CASE
                WHEN mn1_is_zero AND w1_is_zero AND d1_is_zero THEN 'MN1+W1+D1'
                WHEN mn1_is_zero AND w1_is_zero THEN 'MN1+W1'
                WHEN mn1_is_zero AND d1_is_zero THEN 'MN1+D1'
                WHEN w1_is_zero AND d1_is_zero THEN 'W1+D1'
                WHEN mn1_is_zero THEN 'MN1'
                WHEN w1_is_zero THEN 'W1'
                WHEN d1_is_zero THEN 'D1'
                ELSE '-'
            END AS zero_pattern,
            (mn1_state_hex || '/' || w1_state_hex || '/' || d1_state_hex) AS state_triplet
        FROM flags
    ),
    lagged AS (
        SELECT
            *,
            LAG(mn1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_mn1_state_hex,
            LAG(w1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_w1_state_hex,
            LAG(d1_state_hex) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_d1_state_hex,
            LAG(ef_count) OVER (PARTITION BY stock_code ORDER BY state_date) AS prev_ef_count
        FROM derived
    )
    SELECT
        d.stock_code,
        {select_meta}
        d.state_date,
        d.mn1_state_hex,
        d.w1_state_hex,
        d.d1_state_hex,
        d.mn1_state_score,
        d.w1_state_score,
        d.d1_state_score,
        d.mn1_is_ef,
        d.w1_is_ef,
        d.d1_is_ef,
        d.mn1_is_ab,
        d.w1_is_ab,
        d.d1_is_ab,
        d.mn1_is_zero,
        d.w1_is_zero,
        d.d1_is_zero,
        d.ef_count,
        d.ef_pattern,
        d.ab_count,
        d.ab_pattern,
        d.zero_count,
        d.zero_pattern,
        d.state_triplet,
        CASE
            WHEN d.prev_mn1_state_hex IS NULL THEN FALSE
            ELSE (
                (d.mn1_state_hex IS DISTINCT FROM d.prev_mn1_state_hex)
                OR (d.w1_state_hex IS DISTINCT FROM d.prev_w1_state_hex)
                OR (d.d1_state_hex IS DISTINCT FROM d.prev_d1_state_hex)
            )
        END AS state_change_flag,
        (d.ef_count - d.prev_ef_count) AS ef_change,
        CASE
            WHEN d.prev_mn1_state_hex IS NULL THEN '初始状态'
            WHEN (d.mn1_state_hex IS DISTINCT FROM d.prev_mn1_state_hex)
                 OR (d.w1_state_hex IS DISTINCT FROM d.prev_w1_state_hex)
                 OR (d.d1_state_hex IS DISTINCT FROM d.prev_d1_state_hex)
            THEN COALESCE(d.prev_mn1_state_hex || '/' || d.prev_w1_state_hex || '/' || d.prev_d1_state_hex, '-')
                 || ' -> ' || d.mn1_state_hex || '/' || d.w1_state_hex || '/' || d.d1_state_hex
            ELSE '-'
        END AS transition_label,
        d.close,
        d.volume,
        d.state_date AS as_of_date
    FROM lagged d
    {join_meta}
    {where_sql}
    ORDER BY d.state_date DESC, d.stock_code
    """
    return sql, params


def _compute_top50_codes(con: duckdb.DuckDBPyConnection, anchor_date: date) -> list[str]:
    """按最新日期 State 强度取 Top50。"""
    rows = con.execute(
        """
        SELECT stock_code
        FROM d1_perspective_state
        WHERE state_date = ?
        ORDER BY ef_count DESC,
                 ABS(mn1_state_score) + ABS(w1_state_score) + ABS(d1_state_score) DESC,
                 stock_code
        LIMIT 50
        """,
        [anchor_date],
    ).fetchall()
    return [r[0] for r in rows]


def _row_to_dict(row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    """把 DuckDB 行转换为 dict，并做 JSON 友好序列化。"""
    result: dict[str, Any] = {}
    for col, val in zip(columns, row):
        if isinstance(val, date):
            val = val.isoformat()
        result[col] = val
    return result


def _attach_fundamental(con: duckdb.DuckDBPyConnection) -> bool:
    """如果 fundamental DB 存在，则 attach 为 fund。返回是否 attach 成功。"""
    fundamental_db = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
    if not fundamental_db.exists():
        return False
    try:
        con.execute(f"ATTACH IF NOT EXISTS '{fundamental_db}' AS fund (READ_ONLY)")
        return True
    except Exception as exc:
        log.warning("ATTACH fundamental DB 失败: %s", exc)
        return False


def _compute_full_stats(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any],
) -> dict[str, int]:
    """基于 core 查询计算全结果统计：总行数、股票数、EF/A/B/0 行数。"""
    stats_sql = f"""
    WITH core AS ({sql})
    SELECT
        COUNT(*) AS row_count,
        COUNT(DISTINCT stock_code) AS symbol_count,
        COUNT(*) FILTER (WHERE ef_count > 0) AS ef_row_count,
        COUNT(*) FILTER (WHERE ab_count > 0) AS ab_row_count,
        COUNT(*) FILTER (WHERE zero_count > 0) AS zero_row_count
    FROM core
    """
    row = con.execute(stats_sql, params).fetchone()
    return {
        "row_count": row[0] if row else 0,
        "symbol_count": row[1] if row else 0,
        "ef_row_count": row[2] if row else 0,
        "ab_row_count": row[3] if row else 0,
        "zero_row_count": row[4] if row else 0,
    }


def _find_materialized_db(target_date: date) -> Path | None:
    """查找对应日期的预计算表文件。"""
    candidate = STATE_TIMELINE_MATERIALIZED_DIR / f"state_timeline_daily_{target_date.strftime('%Y%m%d')}.duckdb"
    if candidate.exists() and candidate.stat().st_size > 0:
        return candidate
    return None


def _build_materialized_where_clause(
    filters: dict[str, Any],
    effective_symbols: list[str] | None,
    force_empty: bool = False,
) -> tuple[str, list[Any]]:
    """为物化表构建 WHERE 子句与参数（与 _build_core_query 过滤语义保持一致）。"""
    params: list[Any] = []
    parts: list[str] = []

    if force_empty:
        parts.append("FALSE")
    elif effective_symbols:
        placeholders = ", ".join(["?"] * len(effective_symbols))
        parts.append(f"stock_code IN ({placeholders})")
        params.extend(effective_symbols)

    bool_fields = [
        "mn1_is_ef", "w1_is_ef", "d1_is_ef",
        "mn1_is_ab", "w1_is_ab", "d1_is_ab",
        "mn1_is_zero", "w1_is_zero", "d1_is_zero",
    ]
    for field in bool_fields:
        value = _parse_bool_param(filters.get(field))
        if value is not None:
            parts.append(f"{field} = ?")
            params.append(value)

    for pattern_field in ("ef_pattern_any", "ab_pattern_any", "zero_pattern_any"):
        value = filters.get(pattern_field)
        if not value:
            continue
        if isinstance(value, str):
            patterns = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, list):
            patterns = [str(p).strip() for p in value if str(p).strip()]
        else:
            patterns = []
        if not patterns:
            continue
        target = pattern_field.replace("_pattern_any", "_pattern")
        placeholders = ", ".join(["?"] * len(patterns))
        parts.append(f"{target} IN ({placeholders})")
        params.extend(patterns)

    industry = filters.get("industry_l1")
    if industry:
        if isinstance(industry, str):
            industries = [i.strip() for i in industry.split(",") if i.strip()]
        elif isinstance(industry, list):
            industries = [str(i).strip() for i in industry if str(i).strip()]
        else:
            industries = []
        if industries:
            placeholders = ", ".join(["?"] * len(industries))
            parts.append(f"COALESCE(industry_l1, '未分类') IN ({placeholders})")
            params.extend(industries)

    where_sql = "WHERE " + " AND ".join(parts) if parts else ""
    return where_sql, params


def _query_materialized(
    materialized_db: Path,
    target_date: date,
    filters: dict[str, Any],
    effective_symbols: list[str] | None,
    force_empty: bool,
    page: int,
    page_size: int,
    format: str,
    fetch_all: bool,
) -> tuple[list[tuple[Any, ...]], list[str], dict[str, int]]:
    """从物化表读取数据。

    返回：rows（已按分页处理）、columns、stats（全结果统计）
    """
    con = duckdb.connect(str(materialized_db), read_only=True)
    try:
        where_sql, params = _build_materialized_where_clause(
            filters, effective_symbols, force_empty=force_empty
        )

        # 先取全部匹配行做统计（单日全市场最多 ~5500 行，内存可承受）
        count_sql = f"""
            SELECT
                COUNT(*),
                COUNT(DISTINCT stock_code),
                COUNT(*) FILTER (WHERE ef_count > 0),
                COUNT(*) FILTER (WHERE ab_count > 0),
                COUNT(*) FILTER (WHERE zero_count > 0)
            FROM state_timeline_daily
            {where_sql}
        """
        count_row = con.execute(count_sql, params).fetchone()
        stats = {
            "row_count": count_row[0] if count_row else 0,
            "symbol_count": count_row[1] if count_row else 0,
            "ef_row_count": count_row[2] if count_row else 0,
            "ab_row_count": count_row[3] if count_row else 0,
            "zero_row_count": count_row[4] if count_row else 0,
        }

        is_csv = format.lower() == "csv"
        if is_csv or fetch_all:
            sql = f"""
                SELECT * FROM state_timeline_daily
                {where_sql}
                ORDER BY state_date DESC, stock_code
            """
            rows = con.execute(sql, params).fetchall()
        else:
            offset = max(0, (page - 1)) * page_size
            sql = f"""
                SELECT * FROM state_timeline_daily
                {where_sql}
                ORDER BY state_date DESC, stock_code
                LIMIT ? OFFSET ?
            """
            rows = con.execute(sql, params + [page_size, offset]).fetchall()

        columns = [d[0] for d in con.description]
        return rows, columns, stats
    finally:
        try:
            con.close()
        except Exception:
            pass


def _build_materialized_response(
    rows: list[tuple[Any, ...]],
    columns: list[str],
    stats: dict[str, int],
    from_date: date,
    to_date: date,
    query_info: dict[str, Any],
    format: str,
) -> dict[str, Any]:
    """从物化表查询结果构建 response，结构与 CTE 路径保持一致。"""
    row_dicts = [_row_to_dict(r, columns) for r in rows]

    is_csv = format.lower() == "csv"
    if is_csv:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        for row in row_dicts:
            writer.writerow(row)
        return {
            "ok": True,
            "csv": output.getvalue(),
            "meta": {
                "row_count": stats["row_count"],
                "symbol_count": stats["symbol_count"],
                "ef_row_count": stats["ef_row_count"],
                "ab_row_count": stats["ab_row_count"],
                "zero_row_count": stats["zero_row_count"],
                "date_min": from_date.isoformat(),
                "date_max": to_date.isoformat(),
                "as_of_date": to_date.isoformat(),
            },
        }

    return {
        "ok": True,
        "query": query_info,
        "meta": {
            "row_count": stats["row_count"],
            "symbol_count": stats["symbol_count"],
            "ef_row_count": stats["ef_row_count"],
            "ab_row_count": stats["ab_row_count"],
            "zero_row_count": stats["zero_row_count"],
            "date_min": from_date.isoformat(),
            "date_max": to_date.isoformat(),
            "as_of_date": to_date.isoformat(),
        },
        "rows": row_dicts,
    }


def query_state_timeline(
    symbols: str | None = None,
    symbol_set: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    days: int | None = None,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 100,
    format: str = "json",
    user_key: str | None = None,
    fetch_all: bool = False,
) -> dict[str, Any]:
    """查询 State Timeline 长表。

    参数：
      symbols: 逗号分隔的股票代码，或 'all'
      symbol_set: 命名集合，当前支持 'top50' / 'watchlist'
      date_from/date_to: 绝对日期
      days: 相对窗口天数
      filters: 布尔/模式/行业过滤字典
      page/page_size: 分页（CSV 导出时忽略分页，返回全部）
      format: 'json' 或 'csv'
      user_key: 用于读取用户 watchlist（symbol_set=watchlist 时生效）
      fetch_all: 内部只读模式，返回全部匹配行，不受分页上限限制
    """
    filters = filters or {}
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    foundation_db = find_foundation_db()
    if not foundation_db:
        return {"ok": False, "error": "Foundation DB 不存在"}

    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        has_fundamental = _attach_fundamental(con)

        from_date, to_date = _resolve_date_range(
            con,
            _parse_date_param(date_from),
            _parse_date_param(date_to),
            days,
        )

        symbol_list: list[str] | None = None
        if symbols and symbols.strip().lower() != "all":
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

        top50_codes: list[str] | None = None
        if symbol_set and symbol_set.lower() == "top50":
            top50_codes = _compute_top50_codes(con, to_date)

        watchlist_codes: list[str] | None = None
        if symbol_set and symbol_set.lower() == "watchlist":
            watchlist_codes = _resolve_watchlist_codes(user_key or "")

        # 预计算表切换：单日查询且开关打开时，优先走物化表
        materialized_db: Path | None = None
        if USE_STATE_TIMELINE_MATERIALIZED and from_date == to_date:
            materialized_db = _find_materialized_db(to_date)

        if materialized_db:
            effective_symbols: list[str] | None = None
            force_empty = False
            if symbol_list:
                effective_symbols = [_canonical_stock_code(s) for s in symbol_list if s.strip()]
            elif symbol_set and symbol_set.lower() == "top50" and top50_codes:
                effective_symbols = top50_codes
            elif symbol_set and symbol_set.lower() == "watchlist":
                if watchlist_codes:
                    effective_symbols = watchlist_codes
                else:
                    force_empty = True

            rows, columns, stats = _query_materialized(
                materialized_db,
                to_date,
                filters,
                effective_symbols,
                force_empty,
                page,
                page_size,
                format,
                fetch_all,
            )
            query_info = {
                "symbols": symbols,
                "symbol_set": symbol_set,
                "date_from": from_date.isoformat(),
                "date_to": to_date.isoformat(),
                "days": days,
                "filters": filters,
                "page": page,
                "page_size": page_size,
            }
            return _build_materialized_response(
                rows, columns, stats, from_date, to_date, query_info, format
            )

        sql, params = _build_core_query(
            symbol_list,
            symbol_set,
            from_date,
            to_date,
            filters,
            top50_codes,
            watchlist_codes,
            has_fundamental,
        )

        # 全结果统计（基于过滤后的全部行）
        stats = _compute_full_stats(con, sql, params)

        # 是否导出 CSV：CSV 返回全部匹配行，不做分页
        is_csv = format.lower() == "csv"
        should_fetch_all = is_csv or fetch_all

        if should_fetch_all:
            rows = con.execute(sql, params).fetchall()
        else:
            offset = max(0, (page - 1)) * page_size
            paged_sql = f"""
            WITH core AS ({sql})
            SELECT * FROM core
            LIMIT ? OFFSET ?
            """
            paged_params = params + [page_size, offset]
            rows = con.execute(paged_sql, paged_params).fetchall()

        columns = [d[0] for d in con.description]
        row_dicts = [_row_to_dict(r, columns) for r in rows]

        # 展示别名：保留在输出层，不写回 Foundation
        mapping_path = ROOT / "config" / "state_human_mapping.json"
        alias_map: dict[str, str] = {}
        try:
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            alias_map = {str(k).upper(): str(v) for k, v in mapping.get("hex_to_name", {}).items()}
        except Exception:
            pass

        for row in row_dicts:
            aliases = []
            for tf in ("mn1", "w1", "d1"):
                raw_hex = str(row.get(f"{tf}_state_hex") or "").strip()
                is_negative = raw_hex.startswith("-")
                hex_text = raw_hex[1:] if is_negative else raw_hex
                try:
                    key = str(int(hex_text, 16))
                except Exception:
                    key = hex_text.upper()
                name = alias_map.get(key, "未知")
                if is_negative:
                    name = f"逆位{name}"
                aliases.append(name)
            row["display_alias"] = "/".join(aliases)

        if is_csv:
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=columns + ["display_alias"])
            writer.writeheader()
            for row in row_dicts:
                writer.writerow(row)
            return {
                "ok": True,
                "csv": output.getvalue(),
                "meta": {
                    "row_count": stats["row_count"],
                    "symbol_count": stats["symbol_count"],
                    "ef_row_count": stats["ef_row_count"],
                    "ab_row_count": stats["ab_row_count"],
                    "zero_row_count": stats["zero_row_count"],
                    "date_min": from_date.isoformat(),
                    "date_max": to_date.isoformat(),
                    "as_of_date": to_date.isoformat(),
                },
            }

        return {
            "ok": True,
            "query": {
                "symbols": symbols,
                "symbol_set": symbol_set,
                "date_from": from_date.isoformat(),
                "date_to": to_date.isoformat(),
                "days": days,
                "filters": filters,
                "page": page,
                "page_size": page_size,
            },
            "meta": {
                "row_count": stats["row_count"],
                "symbol_count": stats["symbol_count"],
                "ef_row_count": stats["ef_row_count"],
                "ab_row_count": stats["ab_row_count"],
                "zero_row_count": stats["zero_row_count"],
                "date_min": from_date.isoformat(),
                "date_max": to_date.isoformat(),
                "as_of_date": to_date.isoformat(),
            },
            "rows": row_dicts,
        }
    except Exception as exc:
        log.exception("State Timeline 查询失败")
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            con.close()
        except Exception:
            pass


def query_stock_timeline(
    stock_code: str,
    days: int = 30,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """查询单只股票最近 N 天 State 轨迹。"""
    return query_state_timeline(
        symbols=stock_code,
        days=days,
        date_from=date_from,
        date_to=date_to,
        page=1,
        page_size=10000,
        fetch_all=True,
    )
