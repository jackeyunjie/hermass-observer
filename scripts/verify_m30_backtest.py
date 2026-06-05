#!/usr/bin/env python3
"""M30 回测快速验收脚本 — 30 秒内完成。

Usage:
    .venv/bin/python scripts/verify_m30_backtest.py

验收项：
1. 旧 Foundation DB 能跑（无 M30 列）
2. 新 Foundation DB 能跑（有 M30 列）
3. require_m30_breakout=False 与 True 的信号数对比
4. m30_price_breakout 不再全 0
5. m30_ma20_ready 参与过滤
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.engine import load_state_data_from_duckdb
from strategy_rules.ou_bollinger_adx.strategy import ou_bollinger_adx_signal, OUConfig


def check_m30_schema(db_path: Path) -> dict:
    """检查 M30 字段命名是否与当前代码一致。"""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cols = {row[0] for row in con.execute("DESCRIBE d1_perspective_state").fetchall()}
    finally:
        con.close()

    return {
        "has_intraday_prev_high": "m30_intraday_prev_high" in cols,
        "has_stale_prev20_high": "m30_prev20_high" in cols,
        "has_old_high_20": "m30_high_20" in cols,
    }


def count_signals(states: list[dict], require_m30: bool) -> int:
    """统计给定状态下产生的信号数。"""
    cfg = OUConfig(require_m30_breakout=require_m30)
    count = 0
    for state in states:
        result = ou_bollinger_adx_signal(state, cfg)
        if result is not None:
            count += 1
    return count


def verify_foundation(db_path: Path, date_str: str, label: str) -> dict:
    """验证单个 Foundation DB。"""
    print(f"\n=== {label}: {db_path.name} ({date_str}) ===")

    try:
        states_by_date = load_state_data_from_duckdb(db_path, date_str, date_str)
    except Exception as e:
        print(f"  ❌ 加载失败: {e}")
        return {"ok": False, "error": str(e)}

    states = states_by_date.get(date_str, [])
    if not states:
        print(f"  ❌ 无数据")
        return {"ok": False, "error": "no data"}

    print(f"  总股票数: {len(states)}")

    # 检查 M30 字段
    sample = states[0]
    has_m30 = sample.get("m30_adx14") is not None and sample.get("m30_adx14") > 0
    print(f"  M30 数据: {'✅ 有' if has_m30 else '⚪ 无'}")

    # m30_price_breakout 分布
    pb_count = sum(1 for s in states if s.get("m30_price_breakout") == 1)
    print(f"  m30_price_breakout=1: {pb_count}")

    # m30_ma20_ready 分布
    ma20_ready_count = sum(1 for s in states if s.get("m30_ma20_ready", False))
    print(f"  m30_ma20_ready=True: {ma20_ready_count}")

    # 信号数对比
    sig_false = count_signals(states, require_m30=False)
    sig_true = count_signals(states, require_m30=True)
    print(f"  信号数 (require_m30=False): {sig_false}")
    print(f"  信号数 (require_m30=True):  {sig_true}")

    return {
        "ok": True,
        "total": len(states),
        "has_m30": has_m30,
        "price_breakout_count": pb_count,
        "ma20_ready_count": ma20_ready_count,
        "signals_false": sig_false,
        "signals_true": sig_true,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M30 回测快速验收")
    parser.add_argument(
        "--old-db",
        type=Path,
        default=ROOT / "outputs" / "p116_foundation_20260521" / "p116_foundation.duckdb",
        help="旧 Foundation DB（无 M30 列）",
    )
    parser.add_argument(
        "--new-db",
        type=Path,
        default=ROOT / "outputs" / "p116_foundation_20260602" / "p116_foundation.duckdb",
        help="新 Foundation DB（有 M30 列）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("M30 回测快速验收")
    print("=" * 60)

    # 1. 旧 Foundation DB (无 M30 列)
    old_result = verify_foundation(args.old_db, "2026-05-21", "旧 DB")

    # 2. 新 Foundation DB (有 M30 列)
    new_result = verify_foundation(args.new_db, "2026-06-02", "新 DB")
    schema_result = check_m30_schema(args.new_db) if new_result["ok"] else {}

    # 汇总
    print("\n" + "=" * 60)
    print("验收结果汇总")
    print("=" * 60)

    all_pass = True

    # 验收 1: 旧 DB 能跑
    if old_result["ok"]:
        print("✅ 旧 Foundation DB 能跑")
    else:
        print("❌ 旧 Foundation DB 失败")
        all_pass = False

    # 验收 2: 新 DB 能跑
    if new_result["ok"]:
        print("✅ 新 Foundation DB 能跑")
    else:
        print("❌ 新 Foundation DB 失败")
        all_pass = False

    # 验收 2b: 新 DB 字段命名与当前代码一致
    if schema_result.get("has_intraday_prev_high") and not schema_result.get("has_stale_prev20_high") and not schema_result.get("has_old_high_20"):
        print("✅ 新 Foundation DB M30 字段命名正确")
    else:
        print(
            "❌ 新 Foundation DB M30 字段命名不一致 "
            f"(intraday_prev_high={schema_result.get('has_intraday_prev_high')}, "
            f"stale_prev20_high={schema_result.get('has_stale_prev20_high')}, "
            f"old_high_20={schema_result.get('has_old_high_20')})"
        )
        all_pass = False

    # 验收 3: price_breakout 不全 0
    if new_result.get("price_breakout_count", 0) > 0:
        print(f"✅ m30_price_breakout 不全 0 ({new_result['price_breakout_count']} 只)")
    else:
        print("❌ m30_price_breakout 全 0")
        all_pass = False

    # 验收 4: ma20_ready 参与过滤
    if new_result.get("ma20_ready_count", 0) > 0:
        print(f"✅ m30_ma20_ready 参与过滤 ({new_result['ma20_ready_count']} 只 ready)")
    else:
        print("❌ m30_ma20_ready 无就绪")
        all_pass = False

    # 验收 5: require_m30_breakout=False 与 True 对比
    if new_result.get("signals_false", 0) >= new_result.get("signals_true", 0):
        print(f"✅ require_m30=False({new_result['signals_false']}) >= True({new_result['signals_true']})")
    else:
        print(f"⚠️  require_m30=False({new_result['signals_false']}) < True({new_result['signals_true']})")

    print("=" * 60)
    if all_pass:
        print("🎉 全部验收通过")
        return 0
    else:
        print("💥 部分验收失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
