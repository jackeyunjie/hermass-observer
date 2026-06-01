#!/usr/bin/env python3
"""数据库性能与完整性审计 — 一次性全量扫描所有 DuckDB。

产出：docs/DB_PERFORMANCE_AUDIT.md
"""

from __future__ import annotations

import time
import json
import duckdb
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
REPORT_PATH = ROOT / "docs" / "DB_PERFORMANCE_AUDIT.md"

PRIMARY_KEY_MAP = {
    "unified_daily_snapshot": ["snapshot_date", "stock_code"],
    "d1_perspective_state": ["stock_code", "state_date"],
    "ifind_excel_facts": ["stock_code", "as_of_date", "metric_name", "report_period", "source_file"],
    "fundamental_quality_score": ["stock_code", "as_of_date"],
    "fundamental_evidence_packet": ["evidence_id"],
    "ifind_derived_metrics": ["stock_code", "as_of_date"],
    "ifind_industry_chain_profile": ["stock_code", "as_of_date"],
    "ifind_tracking_pool": ["stock_code"],
    "stock_research_ledger": ["stock_code", "as_of_date"],
    "strategy_signal_ledger": ["snapshot_date", "stock_code"],
    "daily_bars": ["stock_code", "trade_date"],
    "weekly_bars": ["stock_code", "week_start"],
    "monthly_bars": ["stock_code", "month_start"],
    "d1_mn1_sr": ["stock_code", "as_of"],
    "d1_d_sr": ["stock_code", "as_of"],
    "d1_w_sr": ["stock_code", "as_of"],
    "d1_sr_context": ["stock_code", "as_of"],
    "sr_levels": ["stock_code", "level_date"],
    "market_state_daily": ["snapshot_date"],
    "market_style_regime": ["snapshot_date"],
}

PERF_QUERIES = []


def discover_databases() -> list[Path]:
    return sorted(p for p in OUTPUT_DIR.rglob("*.duckdb") if p.is_file())


def db_summary(db_path: Path, con: duckdb.DuckDBPyConnection) -> dict:
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    table_info = []
    total_rows = 0

    for (tname,) in tables:
        try:
            row_cnt = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
        except Exception:
            row_cnt = -1

        try:
            col_cnt = con.execute(f"SELECT COUNT(*) FROM pragma_table_info('{tname}')").fetchone()[0]
        except Exception:
            col_cnt = -1

        pk_info = PRIMARY_KEY_MAP.get(tname)

        try:
            size_bytes = con.execute(
                f"SELECT estimated_size FROM duckdb_tables() WHERE table_name = '{tname}'"
            ).fetchone()
            size_bytes = int(size_bytes[0]) if size_bytes and size_bytes[0] else -1
        except Exception:
            size_bytes = -1

        table_info.append(
            {
                "table_name": tname,
                "row_count": row_cnt,
                "column_count": col_cnt,
                "expected_pk": pk_info,
                "estimated_size_bytes": size_bytes,
                "estimated_size_mb": round(size_bytes / 1024 / 1024, 2) if size_bytes > 0 else None,
            }
        )
        if row_cnt > 0:
            total_rows += row_cnt

    disk_size = db_path.stat().st_size

    return {
        "db_path": str(db_path),
        "db_name": db_path.parent.name + "/" + db_path.name,
        "disk_size_bytes": disk_size,
        "disk_size_mb": round(disk_size / 1024 / 1024, 2),
        "table_count": len(tables),
        "total_rows": total_rows,
        "tables": table_info,
    }


def check_pk_unique(con: duckdb.DuckDBPyConnection, tname: str, pk_cols: list[str]) -> dict:
    cols = ", ".join(f'"{c}"' for c in pk_cols)
    try:
        total = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
        unique = con.execute(
            f'SELECT COUNT(*) FROM (SELECT {cols} FROM "{tname}" GROUP BY {cols})'
        ).fetchone()[0]
        dup_count = total - unique
        if dup_count > 0:
            samples = con.execute(
                f'SELECT {cols}, COUNT(*) as cnt FROM "{tname}" GROUP BY {cols} HAVING COUNT(*) > 1 ORDER BY cnt DESC LIMIT 5'
            ).fetchall()
        else:
            samples = []
        return {
            "table": tname,
            "pk_columns": pk_cols,
            "total_rows": total,
            "unique_rows": unique,
            "duplicate_count": dup_count,
            "is_unique": dup_count == 0,
            "dup_samples": [dict(zip(pk_cols + ["dup_cnt"], s)) for s in samples],
        }
    except Exception as e:
        return {
            "table": tname,
            "pk_columns": pk_cols,
            "error": str(e),
        }


def check_cross_db_integrity(con_main: duckdb.DuckDBPyConnection, main_path: str) -> list[dict]:
    """检查统一底座 vs 各源数据表的 stock_code 交集"""
    results = []
    try:
        unified_codes = set(
            r[0]
            for r in con_main.execute(
                "SELECT DISTINCT stock_code FROM unified_daily_snapshot WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM unified_daily_snapshot)"
            ).fetchall()
        )
    except Exception:
        return [{"check": "unified_daily_snapshot", "error": "table not found"}]

    source_dbs = {
        "p116_foundation_latest": str(sorted(OUTPUT_DIR.glob("p116_foundation_*/p116_foundation.duckdb"))[-1])
        if list(OUTPUT_DIR.glob("p116_foundation_*/p116_foundation.duckdb"))
        else None,
        "fundamental_evidence": str(OUTPUT_DIR / "fundamental" / "fundamental_evidence.duckdb"),
        "strategy_signals": str(OUTPUT_DIR / "strategy_signals" / "strategy_signals.duckdb"),
    }

    for label, src_path in source_dbs.items():
        if not src_path or not Path(src_path).exists():
            results.append({"source": label, "error": "db not found"})
            continue
        try:
            con_main.execute(f"ATTACH '{src_path}' AS _src_{label}")
            if label == "p116_foundation_latest":
                src_codes = set(
                    r[0]
                    for r in con_main.execute(
                        "SELECT DISTINCT stock_code FROM _src_p116_foundation_latest.d1_perspective_state WHERE state_date = (SELECT MAX(state_date) FROM _src_p116_foundation_latest.d1_perspective_state)"
                    ).fetchall()
                )
            elif label == "fundamental_evidence":
                src_codes = set(
                    r[0]
                    for r in con_main.execute(
                        "SELECT DISTINCT stock_code FROM _src_fundamental_evidence.fundamental_quality_score WHERE as_of_date = (SELECT MAX(as_of_date) FROM _src_fundamental_evidence.fundamental_quality_score)"
                    ).fetchall()
                )
            elif label == "strategy_signals":
                src_codes = set(
                    r[0]
                    for r in con_main.execute(
                        "SELECT DISTINCT stock_code FROM _src_strategy_signals.strategy_signal_ledger"
                    ).fetchall()
                )

            common = unified_codes & src_codes
            unified_only = unified_codes - src_codes
            src_only = src_codes - unified_codes

            results.append(
                {
                    "source": label,
                    "unified_count": len(unified_codes),
                    "source_count": len(src_codes),
                    "common_count": len(common),
                    "only_in_unified": len(unified_only),
                    "only_in_source": len(src_only),
                    "coverage_pct": round(len(common) / len(unified_codes) * 100, 1) if unified_codes else 0,
                    "samples_only_in_unified": sorted(unified_only)[:5] if unified_only else [],
                    "samples_only_in_source": sorted(src_only)[:5] if src_only else [],
                }
            )
        except Exception as e:
            results.append({"source": label, "error": str(e)})
        finally:
            try:
                con_main.execute(f"DETACH _src_{label}")
            except Exception:
                pass

    return results


def storage_efficiency(db_path: Path, con: duckdb.DuckDBPyConnection) -> list[dict]:
    """分析每个表的存储效率"""
    results = []
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for (tname,) in tables:
        try:
            row_cnt = con.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            col_cnt = con.execute(f"SELECT COUNT(*) FROM pragma_table_info('{tname}')").fetchone()[0]
            disk_bytes = db_path.stat().st_size
            try:
                est_bytes = con.execute(
                    f"SELECT estimated_size FROM duckdb_tables() WHERE table_name = '{tname}'"
                ).fetchone()
                est_bytes = int(est_bytes[0]) if est_bytes and est_bytes[0] else 0
            except Exception:
                est_bytes = 0

            bytes_per_row = round(est_bytes / row_cnt, 1) if row_cnt > 0 else 0

            results.append(
                {
                    "table": tname,
                    "rows": row_cnt,
                    "cols": col_cnt,
                    "est_size_mb": round(est_bytes / 1024 / 1024, 2),
                    "bytes_per_row": bytes_per_row,
                    "efficiency_note": (
                        "⚠️ 每行 > 500 bytes，可能含冗余宽列"
                        if bytes_per_row > 500
                        else "✅ 行列比合理"
                        if bytes_per_row < 500 and bytes_per_row > 0
                        else "—"
                    ),
                }
            )
        except Exception:
            pass
    return results


def run_performance_baselines() -> list[dict]:
    """在几个典型库上跑性能基线"""
    baselines = []
    targets = {
        "small": str(OUTPUT_DIR / "unified_view" / "unified_daily_snapshot.duckdb"),
        "medium": str(OUTPUT_DIR / "fundamental" / "fundamental_evidence.duckdb"),
    }
    p116_latest = sorted(OUTPUT_DIR.glob("p116_foundation_*/p116_foundation.duckdb"))
    if p116_latest:
        targets["large"] = str(p116_latest[-1])

    queries = {
        "全表扫描 COUNT": "SELECT COUNT(*) FROM {table}",
        "日期筛选（最近一天）": "SELECT COUNT(*) FROM {table} WHERE {date_col} = (SELECT MAX({date_col}) FROM {table})",
        "聚合 GROUP BY": "SELECT {group_col}, COUNT(*) as cnt FROM {table} GROUP BY {group_col} ORDER BY cnt DESC LIMIT 10",
    }

    for label, db_path in targets.items():
        if not Path(db_path).exists():
            continue
        con = duckdb.connect(db_path)

        if label == "small":
            table = "unified_daily_snapshot"
            date_col = "snapshot_date"
            group_col = "d1_state_hex"
        elif label == "medium":
            table = "fundamental_quality_score"
            date_col = "as_of_date"
            group_col = "quality_score"
        else:
            table = "d1_perspective_state"
            date_col = "state_date"
            group_col = "d1_state_hex"

        for qname, qtemplate in queries.items():
            sql = qtemplate.format(table=table, date_col=date_col, group_col=group_col)
            t0 = time.perf_counter()
            try:
                rows = con.execute(sql).fetchall()
                elapsed = time.perf_counter() - t0
                baselines.append(
                    {
                        "db": label,
                        "table": table,
                        "query": qname,
                        "sql": sql[:120],
                        "elapsed_ms": round(elapsed * 1000, 1),
                        "result_rows": len(rows),
                    }
                )
            except Exception as e:
                baselines.append(
                    {
                        "db": label,
                        "table": table,
                        "query": qname,
                        "sql": sql[:120],
                        "error": str(e),
                    }
                )

        # Cross-DB JOIN test
        if label == "small":
            try:
                fund_db = str(OUTPUT_DIR / "fundamental" / "fundamental_evidence.duckdb")
                con.execute(f"ATTACH '{fund_db}' AS _fund")
                t0 = time.perf_counter()
                rows = con.execute("""
                    SELECT u.stock_code, u.d1_state_hex, q.quality_score
                    FROM unified_daily_snapshot u
                    JOIN _fund.fundamental_quality_score q
                      ON u.stock_code = q.stock_code
                    WHERE u.snapshot_date = (SELECT MAX(snapshot_date) FROM unified_daily_snapshot)
                      AND q.as_of_date = (SELECT MAX(as_of_date) FROM _fund.fundamental_quality_score)
                """).fetchall()
                elapsed = time.perf_counter() - t0
                baselines.append(
                    {
                        "db": "small × medium (JOIN)",
                        "table": "unified + fundamental_quality_score",
                        "query": "跨库 JOIN（基本面评分 × 统一底座）",
                        "sql": "unified_daily_snapshot JOIN fundamental_quality_score ON stock_code",
                        "elapsed_ms": round(elapsed * 1000, 1),
                        "result_rows": len(rows),
                    }
                )
                con.execute("DETACH _fund")
            except Exception as e:
                baselines.append(
                    {
                        "db": "small × medium (JOIN)",
                        "query": "跨库 JOIN",
                        "error": str(e),
                    }
                )

        con.close()
    return baselines


def generate_report(
    summaries: list[dict],
    pk_results: list[dict],
    integrity_results: list[dict],
    storage_results: list[list],
    perf_baselines: list[dict],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_disksize = sum(s["disk_size_bytes"] for s in summaries)
    total_rows = sum(s["total_rows"] for s in summaries)

    lines = [
        "# 数据库性能与完整性审计报告",
        f"审计时间：{now}",
        "",
        "---",
        "",
        "## 一、数据库清单",
        "",
        f"| # | 数据库 | 表数 | 总行数 | 磁盘大小 |",
        f"|---|--------|------|--------|----------|",
    ]

    for i, s in enumerate(summaries, 1):
        lines.append(
            f"| {i} | {s['db_name']} | {s['table_count']} | {s['total_rows']:,} | {s['disk_size_mb']} MB |"
        )

    lines += [
        "",
        f"**总计**：{len(summaries)} 个数据库，{total_rows:,} 行，{round(total_disksize / 1024 / 1024 / 1024, 2)} GB",
        "",
        "---",
        "",
        "## 二、各库明细",
        "",
    ]

    for s in summaries:
        lines.append(f"### {s['db_name']}（{s['disk_size_mb']} MB）")
        lines.append("")
        lines.append("| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 主键定义 |")
        lines.append("|------|------|------|-------------|----------|----------|")
        for t in s["tables"]:
            pk_str = ", ".join(t.get("expected_pk") or []) or "—"
            lines.append(
                f"| {t['table_name']} | {t['row_count']:,} | {t['column_count']} | {t.get('estimated_size_mb') or '—'} | {'' if t['row_count'] <= 0 else ''} | {pk_str} |"
            )
        lines.append("")

    # PK
    lines += [
        "---",
        "",
        "## 三、主键唯一性检查",
        "",
    ]
    pk_tables = [r for r in pk_results if "error" not in r]
    pk_errors = [r for r in pk_results if "error" in r]

    lines.append("| 表 | 主键字段 | 总行数 | 唯一值 | 重复数 | 状态 |")
    lines.append("|-----|---------|--------|--------|--------|------|")
    for r in pk_tables:
        status = "✅ 唯一" if r["is_unique"] else f"❌ {r['duplicate_count']}条重复"
        lines.append(
            f"| {r['table']} | {', '.join(r['pk_columns'])} | {r['total_rows']:,} | {r['unique_rows']:,} | {r['duplicate_count']} | {status} |"
        )

    if pk_errors:
        lines.append("")
        lines.append("### 检查失败")
        for r in pk_errors:
            lines.append(f"- **{r['table']}**：{r['error']}")

    duplicate_details = [r for r in pk_tables if not r["is_unique"]]
    if duplicate_details:
        lines.append("")
        lines.append("### 重复详情")
        for r in duplicate_details:
            lines.append(f"- **{r['table']}**：{r['duplicate_count']}条重复")
            for s in r.get("dup_samples", []):
                lines.append(f"  - {s}")

    # Integrity
    lines += [
        "",
        "---",
        "",
        "## 四、跨库关联完整性",
        "",
        "以统一底座（unified_daily_snapshot）最新快照为基准，对比各源数据表的 stock_code 交集。",
        "",
        "| 源库 | 统一底座标的数 | 源库标的数 | 交集 | 仅底座 | 仅源库 | 覆盖率 |",
        "|------|-------------|-----------|------|--------|--------|--------|",
    ]
    for r in integrity_results:
        if "error" in r:
            lines.append(f"| {r['source']} | — | — | — | — | — | ❌ {r['error']} |")
        else:
            lines.append(
                f"| {r['source']} | {r['unified_count']} | {r['source_count']:,} | {r['common_count']} | {r['only_in_unified']} | {r['only_in_source']:,} | {r['coverage_pct']}% |"
            )
            if r.get("samples_only_in_unified"):
                lines.append(
                    f"| → 仅底座有（{r['only_in_unified']}只） | — | — | — | {r['samples_only_in_unified'][:3]}… | — | — |"
                )

    lines += [
        "",
        "---",
        "",
        "## 五、存储效率",
        "",
    ]

    for db_path_str, tbl_list in storage_results:
        lines.append(f"### {Path(db_path_str).parent.name}/{Path(db_path_str).name}")
        lines.append("")
        lines.append("| 表名 | 行数 | 列数 | 预估大小(MB) | 行均字节 | 评估 |")
        lines.append("|------|------|------|-------------|----------|------|")
        for t in tbl_list:
            lines.append(
                f"| {t['table']} | {t['rows']:,} | {t['cols']} | {t['est_size_mb']} | {t['bytes_per_row']} | {t['efficiency_note']} |"
            )
        lines.append("")

    # Performance
    lines += [
        "---",
        "",
        "## 六、性能基线",
        "",
        "| 数据库 | 表 | 查询 | 耗时(ms) | 结果行数 |",
        "|--------|-----|------|----------|----------|",
    ]
    for b in perf_baselines:
        if "error" in b:
            lines.append(f"| {b['db']} | {b['table']} | {b['query']} | ❌ {b['error']} | — |")
        else:
            lines.append(
                f"| {b['db']} | {b['table']} | {b['query']} | {b['elapsed_ms']} | {b['result_rows']:,} |"
            )

    lines += [
        "",
        "---",
        "",
        "## 七、建议与后续行动",
        "",
    ]

    suggestions = []

    # 大库建议
    large_dbs = [s for s in summaries if s["disk_size_mb"] > 500]
    if large_dbs:
        names = ", ".join(s["db_name"] for s in large_dbs)
        suggestions.append(
            f"- **大库优化**：{names} 均超过 500MB，建议启用索引：`CREATE INDEX idx_stock_date ON d1_perspective_state(stock_code, state_date);`"
        )

    # 重复 DB 建议
    db_groups: dict[str, list] = {}
    for s in summaries:
        stem = s["db_name"].split("/")[0]
        db_groups.setdefault(stem, []).append(s)
    for stem, grp in db_groups.items():
        if len(grp) > 1:
            sizes = [g["disk_size_mb"] for g in grp]
            if max(sizes) > 100:
                suggestions.append(
                    f"- **历史版本清理**：`{stem}` 存在 {len(grp)} 个日期版本（{', '.join(str(s['disk_size_mb']) + 'MB' for s in grp)}），合计 {sum(sizes):.0f}MB。建议仅保留最新 2 个版本，旧版归档或删除。"
                )

    # 主键问题
    dup_tbls = [r for r in pk_results if not r.get("is_unique", True) and "error" not in r]
    if dup_tbls:
        names = ", ".join(r["table"] for r in dup_tbls)
        suggestions.append(
            f"- **主键重复**：{names} 存在重复行，建议 `DELETE FROM t WHERE rowid NOT IN (SELECT MIN(rowid) FROM t GROUP BY pk_cols);`"
        )

    # 统一底座覆盖
    for r in integrity_results:
        if r.get("coverage_pct") is not None and r["coverage_pct"] < 50:
            suggestions.append(
                f"- **覆盖缺口**：统一底座与 `{r['source']}` 覆盖率仅 {r['coverage_pct']}%，建议检查为何 {r['only_in_unified']} 只标的不在源库中。"
            )

    if suggestions:
        for sg in suggestions:
            lines.append(sg)
    else:
        lines.append("- 当前未发现严重问题。")

    lines += [
        "",
        "---",
        "",
        f"*报告由 `scripts/db_audit.py` 自动生成，审计时间 {now}*",
    ]

    return "\n".join(lines)


def main():
    print("🔍 开始数据库全量审计...")
    dbs = discover_databases()
    print(f"  发现 {len(dbs)} 个 DuckDB 文件")

    summaries = []
    all_pk_results = []
    all_integrity = []
    all_storage = []

    for i, db_path in enumerate(dbs, 1):
        print(f"  [{i}/{len(dbs)}] 扫描 {db_path.parent.name}/{db_path.name}...", end=" ")
        try:
            con = duckdb.connect(str(db_path))
            summary = db_summary(db_path, con)
            summaries.append(summary)
            print(f"{summary['table_count']} tables, {summary['disk_size_mb']} MB")

            # PK check on known tables
            for tbl in summary["tables"]:
                if tbl["expected_pk"] and tbl["row_count"] > 0:
                    pk_r = check_pk_unique(con, tbl["table_name"], tbl["expected_pk"])
                    all_pk_results.append(pk_r)
                    if not pk_r.get("is_unique", True):
                        print(f"    ⚠️  {tbl['table_name']} 主键重复: {pk_r.get('duplicate_count')}")

            # Storage efficiency
            tbl_storage = storage_efficiency(db_path, con)
            all_storage.append((str(db_path), tbl_storage))

            con.close()
        except Exception as e:
            print(f"❌ {e}")
            summaries.append(
                {
                    "db_path": str(db_path),
                    "db_name": db_path.parent.name + "/" + db_path.name,
                    "disk_size_bytes": db_path.stat().st_size,
                    "disk_size_mb": round(db_path.stat().st_size / 1024 / 1024, 2),
                    "table_count": 0,
                    "total_rows": 0,
                    "tables": [],
                    "error": str(e),
                }
            )

    # Integrity
    print("  检查跨库完整性...")
    unified_path = OUTPUT_DIR / "unified_view" / "unified_daily_snapshot.duckdb"
    if unified_path.exists():
        con_main = duckdb.connect(str(unified_path))
        all_integrity = check_cross_db_integrity(con_main, str(unified_path))
        con_main.close()

    # Performance
    print("  运行性能基线...")
    perf_baselines = run_performance_baselines()

    # Generate
    print("  生成报告...")
    report = generate_report(summaries, all_pk_results, all_integrity, all_storage, perf_baselines)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(f"\n✅ 审计完成 → {REPORT_PATH}")
    print(f"   {len(dbs)} 个数据库，{sum(s['total_rows'] for s in summaries):,} 行")
    print(
        f"   主键检查：{len(all_pk_results)} 表，{sum(1 for r in all_pk_results if not r.get('is_unique', True))} 个异常"
    )
    print(f"   跨库完整性：{len(all_integrity)} 项")
    print(f"   性能基线：{len(perf_baselines)} 条")


if __name__ == "__main__":
    main()
