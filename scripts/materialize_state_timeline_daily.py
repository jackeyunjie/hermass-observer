#!/usr/bin/env python3
"""State Timeline Observer 每日预计算表物化脚本。

读取最新 Foundation DB，生成当日的 State Timeline 预计算 DuckDB：
    outputs/state_timeline/state_timeline_daily_YYYYMMDD.duckdb

用法:
    .venv/bin/python scripts/materialize_state_timeline_daily.py --date 2026-07-02
    .venv/bin/python scripts/materialize_state_timeline_daily.py               # 使用 Foundation DB 最新日期
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.services.state_timeline_observer import (
    _attach_fundamental,
    _build_core_query,
    _resolve_date_range,
    find_foundation_db,
)

log = logging.getLogger("hermass.scripts.materialize_state_timeline_daily")

OUTPUT_DIR = ROOT / "outputs" / "state_timeline"

# 物化表固定字段顺序（与 _build_core_query SELECT 一致，并追加 display_alias）
# 注意：_build_core_query 的 SELECT 中已包含 state_change_flag/ef_change/transition_label
MATERIALIZED_COLUMNS = [
    ("stock_code", "VARCHAR"),
    ("stock_name", "VARCHAR"),
    ("industry_l1", "VARCHAR"),
    ("state_date", "DATE"),
    ("mn1_state_hex", "VARCHAR"),
    ("w1_state_hex", "VARCHAR"),
    ("d1_state_hex", "VARCHAR"),
    ("mn1_state_score", "INTEGER"),
    ("w1_state_score", "INTEGER"),
    ("d1_state_score", "INTEGER"),
    ("mn1_is_ef", "BOOLEAN"),
    ("w1_is_ef", "BOOLEAN"),
    ("d1_is_ef", "BOOLEAN"),
    ("mn1_is_ab", "BOOLEAN"),
    ("w1_is_ab", "BOOLEAN"),
    ("d1_is_ab", "BOOLEAN"),
    ("mn1_is_zero", "BOOLEAN"),
    ("w1_is_zero", "BOOLEAN"),
    ("d1_is_zero", "BOOLEAN"),
    ("ef_count", "INTEGER"),
    ("ef_pattern", "VARCHAR"),
    ("ab_count", "INTEGER"),
    ("ab_pattern", "VARCHAR"),
    ("zero_count", "INTEGER"),
    ("zero_pattern", "VARCHAR"),
    ("state_triplet", "VARCHAR"),
    ("state_change_flag", "BOOLEAN"),
    ("ef_change", "INTEGER"),
    ("transition_label", "VARCHAR"),
    ("close", "DOUBLE"),
    ("volume", "BIGINT"),
    ("as_of_date", "DATE"),
    ("display_alias", "VARCHAR"),
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="State Timeline 每日预计算表物化")
    parser.add_argument(
        "--date",
        default="",
        help="数据日期 YYYY-MM-DD，默认使用 Foundation DB 最新日期",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"输出目录，默认 {OUTPUT_DIR}",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出 DEBUG 日志")
    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_alias_map() -> dict[str, str]:
    """加载 state_human_mapping.json，返回 hex -> 中文名的映射。"""
    mapping_path = ROOT / "config" / "state_human_mapping.json"
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        return {str(k).upper(): str(v) for k, v in mapping.get("hex_to_name", {}).items()}
    except Exception as exc:
        log.warning("读取 state_human_mapping.json 失败: %s", exc)
        return {}


def _compute_display_alias(row: dict[str, Any], alias_map: dict[str, str]) -> str:
    """为单行计算 display_alias，与 web.services.state_timeline_observer 逻辑保持一致。"""
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
    return "/".join(aliases)


def _serialize_value(value: Any) -> Any:
    """把 DuckDB 返回的 date/numpy 标量等转换为 Python 友好类型。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def materialize_state_timeline_daily(
    target_date: date | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """物化指定日期的 State Timeline 预计算表。

    返回:
        {"ok": True, "output_path": Path, "row_count": int, "as_of_date": str}
        或 {"ok": False, "error": str}
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    foundation_db = find_foundation_db()
    if not foundation_db:
        return {"ok": False, "error": "Foundation DB 不存在"}

    con = duckdb.connect(str(foundation_db), read_only=True)
    try:
        has_fundamental = _attach_fundamental(con)

        if target_date is None:
            max_date_row = con.execute(
                "SELECT MAX(state_date) FROM d1_perspective_state"
            ).fetchone()
            if not max_date_row or not max_date_row[0]:
                return {"ok": False, "error": "Foundation DB 中无 state_date"}
            target_date = max_date_row[0]

        from_date, to_date = _resolve_date_range(
            con,
            target_date,
            target_date,
            None,
        )
        if from_date != to_date:
            return {"ok": False, "error": "物化脚本只支持单日"}

        sql, params = _build_core_query(
            symbols=None,
            symbol_set=None,
            date_from=from_date,
            date_to=to_date,
            filters={},
            top50_codes=None,
            watchlist_codes=None,
            has_fundamental=has_fundamental,
        )

        log.info("执行物化查询: %s ~ %s", from_date, to_date)
        rows = con.execute(sql, params).fetchall()
        columns = [d[0] for d in con.description]
        row_count = len(rows)
        log.info("查询完成: %d 行", row_count)

        alias_map = _load_alias_map()

        # 构造输出文件路径
        date_str = to_date.strftime("%Y%m%d")
        output_path = output_dir / f"state_timeline_daily_{date_str}.duckdb"

        # 用临时文件原子写入（DuckDB 需要自己创建文件，先删除 mkstemp 留下的空文件）
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".duckdb", prefix="state_timeline_daily_", dir=output_dir
        )
        os.close(tmp_fd)
        tmp_file = Path(tmp_path)
        try:
            tmp_file.unlink(missing_ok=True)
            out_con = duckdb.connect(str(tmp_file))
            try:
                # 建表
                col_defs = ", ".join(f"{name} {dtype}" for name, dtype in MATERIALIZED_COLUMNS)
                out_con.execute(f"CREATE TABLE state_timeline_daily ({col_defs})")

                # 插入数据
                insert_sql = f"""
                    INSERT INTO state_timeline_daily
                    VALUES ({', '.join(['?'] * len(MATERIALIZED_COLUMNS))})
                """
                insert_rows: list[list[Any]] = []
                for raw_row in rows:
                    row_dict = dict(zip(columns, raw_row))
                    row_dict["display_alias"] = _compute_display_alias(row_dict, alias_map)
                    insert_row = []
                    for col_name, _ in MATERIALIZED_COLUMNS:
                        val = _serialize_value(row_dict.get(col_name))
                        insert_row.append(val)
                    insert_rows.append(insert_row)

                if insert_rows:
                    out_con.executemany(insert_sql, insert_rows)

                # 建索引
                out_con.execute("CREATE INDEX idx_stock_date ON state_timeline_daily(stock_code, state_date)")
                out_con.execute("CREATE INDEX idx_state_date ON state_timeline_daily(state_date)")
                out_con.execute("CREATE INDEX idx_industry ON state_timeline_daily(industry_l1)")
                out_con.execute("CREATE INDEX idx_ef_pattern ON state_timeline_daily(ef_pattern)")
                out_con.execute("CREATE INDEX idx_ab_pattern ON state_timeline_daily(ab_pattern)")
                out_con.execute("CREATE INDEX idx_zero_pattern ON state_timeline_daily(zero_pattern)")

                out_con.execute("CHECKPOINT")
            finally:
                out_con.close()

            # 原子替换
            shutil.move(str(tmp_file), str(output_path))
        except Exception:
            # 清理临时文件
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        log.info("物化完成: %s (%d 行)", output_path, row_count)
        return {
            "ok": True,
            "output_path": output_path,
            "row_count": row_count,
            "as_of_date": to_date.isoformat(),
        }
    except Exception as exc:
        log.exception("物化 State Timeline 失败")
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            con.close()
        except Exception:
            pass


def main() -> int:
    args = _parse_args()
    _setup_logging(args.verbose)

    target_date: date | None = None
    if args.date:
        target_date = date.fromisoformat(args.date)

    output_dir = Path(args.output_dir)
    result = materialize_state_timeline_daily(
        target_date=target_date,
        output_dir=output_dir,
    )

    if not result.get("ok"):
        print(f"失败: {result.get('error')}", file=sys.stderr)
        return 1

    print(f"成功: {result['output_path']} ({result['row_count']} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
