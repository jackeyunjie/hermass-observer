#!/usr/bin/env python3
"""Factor Homeostasis — 因子免疫稳态机制。

每个因子维护一个 ±tolerance_pct 耐受带，在带内波动不触发权重调整。
只有连续超过 consecutive_days 天超出耐受带，才触发调整。

设计理念：
  - 借鉴生物免疫系统的稳态机制，防止因子权重因短期噪声剧烈波动
  - 耐受带内 = 正常波动，免疫系统不响应
  - 连续超带 = 真实信号漂移，触发校正响应

用法：
  python3 scripts/factor_homeostasis.py --date 2026-06-02
  python3 scripts/factor_homeostasis.py --date 2026-06-02 --foundation-db /path/to/foundation.duckdb
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.agents.base_agent import find_foundation_db

# ── 默认配置 ──────────────────────────────────────────────────
DEFAULT_TOLERANCE_PCT = 0.10       # ±10% 耐受带
DEFAULT_CONSECUTIVE_DAYS = 5       # 连续超带 N 天才触发调整
DEFAULT_ADJUSTMENT_CAP = 0.05      # 单次调整幅度上限 5%
DEFAULT_MIN_SAMPLES = 30           # 最少样本数才开始评估
OBSERVATION_DAYS = 5               # 观察期天数（触发调整后进入冷却，防止反复振荡）

# ── 休眠因子配置 ──────────────────────────────────────────────
# 休眠因子 → 唤醒条件映射；满足条件时重新参与稳态评估
DORMANT_FACTORS: dict[str, dict[str, str]] = {
    "solar_term_factor": {
        "description": "节气因子 — 在节气转换前后 3 天活跃",
        "awakening_rule": "check_solar_term_proximity",
    },
    "earnings_season_factor": {
        "description": "财报季因子 — 在 1/4/7/10 月初活跃",
        "awakening_rule": "check_earnings_season",
    },
    "policy_event_factor": {
        "description": "政策事件因子 — 在重大会议前后活跃",
        "awakening_rule": "check_policy_calendar",
    },
}

HOMEOSTASIS_TABLE = "factor_homeostasis"
HOMEOSTASIS_LOG_TABLE = "factor_homeostasis_log"
HOMEOSTASIS_MANIFEST_TABLE = "factor_homeostasis_manifest"


@dataclass
class FactorBand:
    """单个因子的耐受带状态。"""
    factor_name: str
    baseline_value: float           # 基线值（滚动窗口均值）
    tolerance_pct: float            # 耐受带百分比
    upper_bound: float = 0.0
    lower_bound: float = 0.0
    current_value: float = 0.0
    consecutive_days_outside: int = 0
    direction: str = ""             # "above" | "below" | "within"
    triggered: bool = False         # 是否触发调整

    def __post_init__(self):
        self.upper_bound = self.baseline_value * (1 + self.tolerance_pct)
        self.lower_bound = self.baseline_value * (1 - self.tolerance_pct)

    def evaluate(self, new_value: float) -> None:
        """评估新值是否在耐受带内。"""
        self.current_value = new_value
        if new_value > self.upper_bound:
            self.direction = "above"
            self.consecutive_days_outside += 1
        elif new_value < self.lower_bound:
            self.direction = "below"
            self.consecutive_days_outside += 1
        else:
            self.direction = "within"
            self.consecutive_days_outside = 0

    def should_adjust(self, consecutive_threshold: int) -> bool:
        """是否应该触发调整。"""
        self.triggered = self.consecutive_days_outside >= consecutive_threshold
        return self.triggered

    def compute_adjustment(self, cap: float) -> float:
        """计算调整量（有上限保护）。"""
        if not self.triggered:
            return 0.0
        deviation = self.current_value - self.baseline_value
        # 只回拉到耐受带边界，不回到基线
        if self.direction == "above":
            target = self.upper_bound
        else:
            target = self.lower_bound
        raw_adjustment = (target - self.current_value) / max(abs(self.baseline_value), 1e-9)
        # 限幅
        clamped = max(-cap, min(cap, raw_adjustment))
        return round(clamped, 6)

    def to_dict(self, in_observation: bool = False) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "baseline_value": round(self.baseline_value, 6),
            "current_value": round(self.current_value, 6),
            "tolerance_pct": self.tolerance_pct,
            "upper_bound": round(self.upper_bound, 6),
            "lower_bound": round(self.lower_bound, 6),
            "direction": self.direction,
            "consecutive_days_outside": self.consecutive_days_outside,
            "triggered": self.triggered,
            "in_observation": in_observation,
        }


@dataclass
class HomeostasisConfig:
    """全局稳态配置。"""
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT
    consecutive_days: int = DEFAULT_CONSECUTIVE_DAYS
    adjustment_cap: float = DEFAULT_ADJUSTMENT_CAP
    min_samples: int = DEFAULT_MIN_SAMPLES
    # 每个因子可以单独覆盖配置
    factor_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_tolerance(self, factor_name: str) -> float:
        return self.factor_overrides.get(factor_name, {}).get("tolerance_pct", self.tolerance_pct)

    def get_consecutive(self, factor_name: str) -> int:
        return self.factor_overrides.get(factor_name, {}).get("consecutive_days", self.consecutive_days)


def _ensure_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """确保 DuckDB 中存在所需的表。"""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {HOMEOSTASIS_TABLE} (
            factor_name VARCHAR NOT NULL,
            eval_date DATE NOT NULL,
            baseline_value DOUBLE,
            current_value DOUBLE,
            tolerance_pct DOUBLE,
            upper_bound DOUBLE,
            lower_bound DOUBLE,
            direction VARCHAR,
            consecutive_days_outside INTEGER DEFAULT 0,
            triggered BOOLEAN DEFAULT FALSE,
            adjustment_delta DOUBLE DEFAULT 0.0,
            observation_until DATE DEFAULT NULL,
            PRIMARY KEY (factor_name, eval_date)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {HOMEOSTASIS_LOG_TABLE} (
            log_id INTEGER,
            factor_name VARCHAR NOT NULL,
            eval_date DATE NOT NULL,
            event_type VARCHAR NOT NULL,
            old_value DOUBLE,
            new_value DOUBLE,
            adjustment_delta DOUBLE,
            reason VARCHAR,
            created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {HOMEOSTASIS_MANIFEST_TABLE} (
            run_date DATE NOT NULL,
            factors_evaluated INTEGER,
            factors_triggered INTEGER,
            total_adjustments INTEGER,
            schema_version VARCHAR DEFAULT '1.0',
            status VARCHAR DEFAULT 'ok'
        )
    """)


def _compute_factor_baselines(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
    lookback_days: int = 60,
) -> dict[str, float]:
    """从 state_cache / 前向观察数据中计算因子基线值。

    因子列表：
      - ef2_rate: 全市场 EF2 率
      - avg_d1_score: D1 平均 State score
      - avg_w1_score: W1 平均 State score
      - avg_mn1_score: MN1 平均 State score
      - pool_change_rate: 观察池变化率
      - avg_atr_ratio: 平均 ATR 比率
      - sector_dispersion: 行业离散度
    """
    baselines: dict[str, float] = {}

    # EF2 率
    try:
        row = conn.execute(f"""
            SELECT AVG(CASE WHEN ef_count >= 2 THEN 1.0 ELSE 0.0 END) AS ef2_rate
            FROM state_ef_daily
            WHERE state_date BETWEEN CAST('{target_date}' AS DATE) - INTERVAL {lookback_days} DAY
                                 AND CAST('{target_date}' AS DATE)
        """).fetchone()
        baselines["ef2_rate"] = float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        baselines["ef2_rate"] = 0.0

    # D1 / W1 / MN1 平均 score
    for period, col in [("d1", "d1_state_score"), ("w1", "w1_state_score"), ("mn1", "mn1_state_score")]:
        try:
            row = conn.execute(f"""
                SELECT AVG({col}) AS avg_score
                FROM state_ef_daily
                WHERE state_date BETWEEN CAST('{target_date}' AS DATE) - INTERVAL {lookback_days} DAY
                                     AND CAST('{target_date}' AS DATE)
                  AND {col} IS NOT NULL
            """).fetchone()
            baselines[f"avg_{period}_score"] = float(row[0]) if row and row[0] is not None else 0.0
        except Exception:
            baselines[f"avg_{period}_score"] = 0.0

    # ATR ratio 均值
    try:
        row = conn.execute(f"""
            SELECT AVG(d1_atr_ratio_pct) AS avg_atr
            FROM state_ef_daily
            WHERE state_date BETWEEN CAST('{target_date}' AS DATE) - INTERVAL {lookback_days} DAY
                                 AND CAST('{target_date}' AS DATE)
              AND d1_atr_ratio_pct IS NOT NULL
        """).fetchone()
        baselines["avg_atr_ratio"] = float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        baselines["avg_atr_ratio"] = 0.0

    # Pool change rate: 今天 EF2 数 / 昨天 EF2 数 - 1
    try:
        rows = conn.execute(f"""
            SELECT state_date, COUNT(*) AS cnt
            FROM state_ef_daily
            WHERE ef_count >= 2
              AND state_date BETWEEN CAST('{target_date}' AS DATE) - INTERVAL 5 DAY
                                 AND CAST('{target_date}' AS DATE)
            GROUP BY state_date
            ORDER BY state_date DESC
            LIMIT 2
        """).fetchall()
        if len(rows) >= 2 and rows[1][1] > 0:
            baselines["pool_change_rate"] = (rows[0][1] / rows[1][1]) - 1.0
        else:
            baselines["pool_change_rate"] = 0.0
    except Exception:
        baselines["pool_change_rate"] = 0.0

    # Sector dispersion: 行业间 EF2 率标准差
    try:
        row = conn.execute(f"""
            SELECT STDDEV_POP(ef2_rate) AS dispersion
            FROM (
                SELECT
                    COALESCE(m.sw_l1, '未知') AS industry,
                    AVG(CASE WHEN s.ef_count >= 2 THEN 1.0 ELSE 0.0 END) AS ef2_rate
                FROM state_ef_daily s
                LEFT JOIN (
                    SELECT symbol, sw_l1 FROM asset_metadata
                ) m ON s.stock_code = m.symbol
                WHERE s.state_date = CAST('{target_date}' AS DATE)
                GROUP BY COALESCE(m.sw_l1, '未知')
            )
        """).fetchone()
        baselines["sector_dispersion"] = float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        baselines["sector_dispersion"] = 0.0

    return baselines


def _compute_factor_current(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> dict[str, float]:
    """计算当天因子值（同 _compute_factor_baselines 但只看当天）。"""
    return _compute_factor_baselines(conn, target_date, lookback_days=1)


# ── 节气近似日期表（公历） ─────────────────────────────────────
# 每年日期略有浮动，此处取近似固定值用于粗略判断
_SOLAR_TERM_APPROX: list[tuple[int, int, str]] = [
    (1, 6, "小寒"), (1, 20, "大寒"),
    (2, 4, "立春"), (2, 19, "雨水"),
    (3, 6, "惊蛰"), (3, 21, "春分"),
    (4, 5, "清明"), (4, 20, "谷雨"),
    (5, 6, "立夏"), (5, 21, "小满"),
    (6, 6, "芒种"), (6, 21, "夏至"),
    (7, 7, "小暑"), (7, 23, "大暑"),
    (8, 7, "立秋"), (8, 23, "处暑"),
    (9, 8, "白露"), (9, 23, "秋分"),
    (10, 8, "寒露"), (10, 23, "霜降"),
    (11, 7, "立冬"), (11, 22, "小雪"),
    (12, 7, "大雪"), (12, 22, "冬至"),
]


def _is_near_solar_term(target: date, within_days: int = 3) -> bool:
    """判断 target_date 是否在某个节气前后 within_days 天内。"""
    year = target.year
    for month, day, _name in _SOLAR_TERM_APPROX:
        try:
            solar_date = date(year, month, day)
        except ValueError:
            continue
        if abs((target - solar_date).days) <= within_days:
            return True
    return False


def check_dormant_factors(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> list[dict[str, str]]:
    """检查哪些休眠因子应当在 target_date 被唤醒。

    Returns:
        被唤醒因子的信息列表，每项包含 factor_name / description / reason。
    """
    dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    awakened: list[dict[str, str]] = []

    # 1) 节气因子：是否在节气转换前后 3 天
    if _is_near_solar_term(dt, within_days=3):
        info = DORMANT_FACTORS["solar_term_factor"]
        awakened.append({
            "factor_name": "solar_term_factor",
            "description": info["description"],
            "reason": f"日期 {target_date} 临近节气转换（±3 天）",
        })

    # 2) 财报季因子：是否在 1 / 4 / 7 / 10 月
    if dt.month in (1, 4, 7, 10):
        info = DORMANT_FACTORS["earnings_season_factor"]
        awakened.append({
            "factor_name": "earnings_season_factor",
            "description": info["description"],
            "reason": f"月份 {dt.month} 属于财报季",
        })

    # 3) 政策事件因子：简化规则 — 每年 3 月（两会）和 10-11 月（重要会议期）
    if dt.month in (3, 10, 11):
        info = DORMANT_FACTORS["policy_event_factor"]
        awakened.append({
            "factor_name": "policy_event_factor",
            "description": info["description"],
            "reason": f"月份 {dt.month} 属于重大会议窗口期",
        })

    return awakened


def evaluate_homeostasis(
    target_date: str,
    foundation_db: str = "",
    config: Optional[HomeostasisConfig] = None,
) -> dict[str, Any]:
    """执行因子免疫稳态评估。

    Returns:
        包含所有因子评估结果、触发状态、建议调整量的字典。
    """
    if config is None:
        config = HomeostasisConfig()

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return {"status": "error", "errors": ["无可用 Foundation DB"]}
        foundation_db = str(db_path)

    conn = duckdb.connect(foundation_db)
    try:
        _ensure_tables(conn)

        # 兼容迁移：已有表可能缺少 observation_until 列
        try:
            conn.execute(f"""
                ALTER TABLE {HOMEOSTASIS_TABLE}
                ADD COLUMN observation_until DATE DEFAULT NULL
            """)
        except Exception:
            pass  # 列已存在

        # 休眠因子唤醒检测
        awakened_factors = check_dormant_factors(conn, target_date)

        baselines = _compute_factor_baselines(conn, target_date)
        currents = _compute_factor_current(conn, target_date)

        bands: list[FactorBand] = []
        log_entries: list[dict[str, Any]] = []
        observation_set: set[str] = set()  # 处于观察期的因子集合

        for factor_name, baseline in baselines.items():
            tol = config.get_tolerance(factor_name)
            consec_threshold = config.get_consecutive(factor_name)

            band = FactorBand(
                factor_name=factor_name,
                baseline_value=baseline,
                tolerance_pct=tol,
            )

            current_val = currents.get(factor_name, baseline)
            band.evaluate(current_val)

            # 检查观察期（触发调整后 N 天内不再触发新调整，但照常记录耐受带状态）
            in_observation = False
            try:
                obs_row = conn.execute(f"""
                    SELECT observation_until
                    FROM {HOMEOSTASIS_TABLE}
                    WHERE factor_name = '{factor_name}'
                      AND eval_date = (
                          SELECT MAX(eval_date) FROM {HOMEOSTASIS_TABLE}
                          WHERE factor_name = '{factor_name}'
                            AND eval_date < CAST('{target_date}' AS DATE)
                      )
                """).fetchone()
                if obs_row and obs_row[0] is not None:
                    obs_until = obs_row[0]
                    if isinstance(obs_until, str):
                        obs_until = datetime.strptime(obs_until, "%Y-%m-%d").date()
                    current_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
                    if current_dt < obs_until:
                        in_observation = True
                        observation_set.add(factor_name)
            except Exception:
                pass  # 无历史数据或列不存在

            # 检查历史连续天数（从 homeostasis 表读取前几天的状态）
            try:
                history = conn.execute(f"""
                    SELECT direction, consecutive_days_outside
                    FROM {HOMEOSTASIS_TABLE}
                    WHERE factor_name = '{factor_name}'
                      AND eval_date < CAST('{target_date}' AS DATE)
                    ORDER BY eval_date DESC
                    LIMIT {consec_threshold}
                """).fetchall()

                if history and band.direction != "within":
                    # 如果前几天也在同方向超带，累加
                    prev_consecutive = 0
                    for row in history:
                        if row[0] == band.direction:
                            prev_consecutive += 1
                        else:
                            break
                    band.consecutive_days_outside += prev_consecutive
            except Exception:
                pass  # 表可能不存在历史数据

            should_adjust = band.should_adjust(consec_threshold)

            # 观察期内不触发新调整（但仍记录耐受带状态）
            if in_observation and should_adjust:
                band.triggered = False
                should_adjust = False

            adjustment = band.compute_adjustment(config.adjustment_cap) if should_adjust else 0.0
            observation_until_str: Optional[str] = None

            # 写入评估结果
            conn.execute(f"""
                INSERT OR REPLACE INTO {HOMEOSTASIS_TABLE}
                (factor_name, eval_date, baseline_value, current_value,
                 tolerance_pct, upper_bound, lower_bound,
                 direction, consecutive_days_outside, triggered, adjustment_delta,
                 observation_until)
                VALUES (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                factor_name, target_date, band.baseline_value, band.current_value,
                band.tolerance_pct, band.upper_bound, band.lower_bound,
                band.direction, band.consecutive_days_outside, band.triggered, adjustment,
                observation_until_str,
            ])

            # 记录触发事件 & 设置观察期
            if should_adjust:
                # 计算观察期截止日：target_date + OBSERVATION_DAYS
                current_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
                obs_until = current_dt + timedelta(days=OBSERVATION_DAYS)
                observation_until_str = obs_until.strftime("%Y-%m-%d")

                # 回写观察期到刚插入的记录
                conn.execute(f"""
                    UPDATE {HOMEOSTASIS_TABLE}
                    SET observation_until = CAST(? AS DATE)
                    WHERE factor_name = ? AND eval_date = CAST(? AS DATE)
                """, [observation_until_str, factor_name, target_date])

                log_id = conn.execute(f"SELECT COALESCE(MAX(log_id), 0) + 1 FROM {HOMEOSTASIS_LOG_TABLE}").fetchone()[0]
                conn.execute(f"""
                    INSERT INTO {HOMEOSTASIS_LOG_TABLE}
                    (log_id, factor_name, eval_date, event_type, old_value, new_value, adjustment_delta, reason)
                    VALUES (?, ?, CAST(? AS DATE), 'adjustment_triggered', ?, ?, ?, ?)
                """, [
                    log_id, factor_name, target_date,
                    band.baseline_value, band.current_value, adjustment,
                    f"连续 {band.consecutive_days_outside} 天超出 ±{tol*100:.0f}% 耐受带，进入观察期至 {observation_until_str}",
                ])
                log_entries.append({
                    "factor_name": factor_name,
                    "event": "adjustment_triggered",
                    "adjustment_delta": adjustment,
                    "observation_until": observation_until_str,
                    "reason": f"连续 {band.consecutive_days_outside} 天超带，观察期至 {observation_until_str}",
                })

            bands.append(band)

        # 写入 manifest
        factors_triggered = sum(1 for b in bands if b.triggered)
        conn.execute(f"""
            INSERT INTO {HOMEOSTASIS_MANIFEST_TABLE}
            (run_date, factors_evaluated, factors_triggered, total_adjustments)
            VALUES (CAST(? AS DATE), ?, ?, ?)
        """, [target_date, len(bands), factors_triggered, factors_triggered])

        conn.commit()

    finally:
        conn.close()

    result = {
        "status": "ok",
        "date": target_date,
        "config": {
            "tolerance_pct": config.tolerance_pct,
            "consecutive_days": config.consecutive_days,
            "adjustment_cap": config.adjustment_cap,
            "observation_days": OBSERVATION_DAYS,
        },
        "factors_evaluated": len(bands),
        "factors_triggered": sum(1 for b in bands if b.triggered),
        "bands": [b.to_dict(in_observation=(b.factor_name in observation_set)) for b in bands],
        "adjustments": [
            {"factor": b.factor_name, "delta": b.compute_adjustment(config.adjustment_cap)}
            for b in bands if b.triggered and b.factor_name not in observation_set
        ],
        "awakened_factors": awakened_factors,
        "log_entries": log_entries,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor Homeostasis — 因子免疫稳态评估")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                        help="交易日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--foundation-db", default="", help="Foundation DB 路径")
    parser.add_argument("--tolerance-pct", type=float, default=DEFAULT_TOLERANCE_PCT,
                        help=f"耐受带百分比（默认 {DEFAULT_TOLERANCE_PCT}）")
    parser.add_argument("--consecutive-days", type=int, default=DEFAULT_CONSECUTIVE_DAYS,
                        help=f"连续超带天数阈值（默认 {DEFAULT_CONSECUTIVE_DAYS}）")
    parser.add_argument("--check-dormant", action="store_true",
                        help="仅检查休眠因子唤醒状态并输出结果")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    # --check-dormant：仅运行休眠因子检查并退出
    if args.check_dormant:
        db_path = args.foundation_db or ""
        if not db_path:
            found = find_foundation_db(args.date)
            if found is None:
                print(f"[{args.date}] 无可用 Foundation DB", file=sys.stderr)
                return 1
            db_path = str(found)
        conn = duckdb.connect(db_path)
        try:
            _ensure_tables(conn)
            awakened = check_dormant_factors(conn, args.date)
        finally:
            conn.close()

        if args.json:
            print(json.dumps({
                "date": args.date,
                "awakened_factors": awakened,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"=== Dormant Factor Check ({args.date}) ===")
            if awakened:
                for af in awakened:
                    print(f"  [AWAKENED] {af['factor_name']}")
                    print(f"             {af['description']}")
                    print(f"             原因: {af['reason']}")
            else:
                print("  当前无休眠因子被唤醒。")
        return 0

    config = HomeostasisConfig(
        tolerance_pct=args.tolerance_pct,
        consecutive_days=args.consecutive_days,
    )

    result = evaluate_homeostasis(
        target_date=args.date,
        foundation_db=args.foundation_db,
        config=config,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== Factor Homeostasis Report ({args.date}) ===")
        print(f"评估因子数: {result.get('factors_evaluated', 0)}")
        print(f"触发调整数: {result.get('factors_triggered', 0)}")
        print(f"观察期天数: {OBSERVATION_DAYS}")
        print()
        for band in result.get("bands", []):
            if band["triggered"]:
                status = "TRIGGERED"
            elif band["in_observation"]:
                status = "OBSERVATION"
            else:
                status = "stable"
            print(f"  {band['factor_name']:25s} | "
                  f"baseline={band['baseline_value']:.4f} | "
                  f"current={band['current_value']:.4f} | "
                  f"band=[{band['lower_bound']:.4f}, {band['upper_bound']:.4f}] | "
                  f"days_outside={band['consecutive_days_outside']} | "
                  f"{status}")
        if result.get("adjustments"):
            print("\n建议调整:")
            for adj in result["adjustments"]:
                print(f"  {adj['factor']:25s} → delta={adj['delta']:+.4f}")
        if result.get("awakened_factors"):
            print("\n唤醒的休眠因子:")
            for af in result["awakened_factors"]:
                print(f"  {af['factor_name']:30s} | {af['description']} | {af['reason']}")

    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
