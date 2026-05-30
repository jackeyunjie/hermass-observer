#!/usr/bin/env python3
"""
estimate_reward_risk.py

[DEPRECATED — 只读分析模式]

本脚本已降级为仅供研究参考的只读分析工具，不再作为入场/出场决策依据。

原因：以阻力位作为上涨目标会人为设定利润天花板，违背"让利润奔跑"原则。
正确的利润保护由策略出场规则控制（VCP移动止损、2560均线跌破、布林强盗递减均线）。

保留功能：
- 展示 SR 边界位置（支撑/阻力参考）
- 记录 upside/downside 百分比（仅供观察，不做过滤）
- 不再计算 RR ratio，不再标记 high_value

Usage:
    python scripts/estimate_reward_risk.py --date 2026-05-22
"""

import json
import argparse
import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import duckdb


PROJECT_ROOT = Path(__file__).parent.parent
STATE_CACHE_DB = PROJECT_ROOT / "outputs" / "state_cache" / "state_cache.duckdb"
SIGNALS_DIR = PROJECT_ROOT / "outputs" / "strategy_signals"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reward_risk"


@dataclass
class SRRecord:
    obs_date: datetime.date
    period: str
    btype: str
    boundary_price: float
    above_r: bool
    below_s: bool
    distance_pct: float
    d1_close: float


@dataclass
class RREstimate:
    stock_code: str
    stock_name: str
    strategy_id: str
    signal_name: str
    signal_date: str
    current_close: Optional[float] = None
    close_source: str = ""
    close_date: Optional[str] = None
    upside_pct: Optional[float] = None
    downside_pct: Optional[float] = None
    rr_ratio: Optional[float] = None
    confidence: float = 0.0
    upside_method: str = ""
    downside_method: str = ""
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    broken_resistance: Optional[float] = None
    support_period: str = ""
    resistance_period: str = ""
    sr_data_age_days: int = 0
    high_value: bool = False
    tags: list[str] = field(default_factory=list)
    research_only: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_signals(signal_date: str) -> list[dict]:
    file_date = signal_date.replace("-", "")
    path = SIGNALS_DIR / f"strategy_signal_daily_{file_date}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    return [r for r in rows if r.get("signal_type") == "entry" and r.get("reminder_eligible")]


def get_current_close(
    con: duckdb.DuckDBPyConnection, stock_code: str, signal_date: str, max_stale_days: int = 7
) -> tuple[Optional[float], str, Optional[datetime.date]]:
    """Fetch close price for signal date.

    Returns (close_value, source, obs_date)
    Priority:
      1. state_ef_daily on exact signal_date
      2. sr_boundary_daily on exact signal_date
      3. state_ef_daily latest (any date, if within max_stale_days)
      4. sr_boundary_daily latest (any date, if within max_stale_days)
      5. sr_boundary_daily latest (any date, even if stale)
    """
    sig_dt = datetime.date.fromisoformat(signal_date)

    # 1. state_ef_daily exact date
    row = con.execute(
        "SELECT d1_close FROM state_ef_daily WHERE stock_code = ? AND obs_date = ?",
        (stock_code, sig_dt),
    ).fetchone()
    if row:
        return float(row[0]), "state_ef_daily", sig_dt

    # 2. sr_boundary_daily exact date
    row = con.execute(
        "SELECT d1_close FROM sr_boundary_daily WHERE stock_code = ? AND obs_date = ? LIMIT 1",
        (stock_code, sig_dt),
    ).fetchone()
    if row:
        return float(row[0]), "sr_boundary_daily", sig_dt

    # 3. state_ef_daily latest (if fresh enough)
    row = con.execute(
        "SELECT obs_date, d1_close FROM state_ef_daily WHERE stock_code = ? ORDER BY obs_date DESC LIMIT 1",
        (stock_code,),
    ).fetchone()
    if row and (sig_dt - row[0]).days <= max_stale_days:
        return float(row[1]), "state_ef_daily_latest", row[0]

    # 4. sr_boundary_daily latest (if fresh enough)
    row2 = con.execute(
        "SELECT obs_date, d1_close FROM sr_boundary_daily WHERE stock_code = ? ORDER BY obs_date DESC LIMIT 1",
        (stock_code,),
    ).fetchone()
    if row2 and (sig_dt - row2[0]).days <= max_stale_days:
        return float(row2[1]), "sr_boundary_daily_latest", row2[0]

    # 5. Fallback to whichever is newer (even if stale)
    candidates = []
    if row:
        candidates.append((row[0], float(row[1]), "state_ef_daily_latest"))
    if row2:
        candidates.append((row2[0], float(row2[1]), "sr_boundary_daily_latest"))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best = candidates[0]
        return best[1], best[2], best[0]

    return None, "", None


def get_latest_sr(con: duckdb.DuckDBPyConnection, stock_code: str) -> list[SRRecord]:
    """Get latest SR record per (period, type)."""
    rows = con.execute(
        """
        SELECT obs_date, boundary_period, boundary_type, boundary_price,
               above_resistance, below_support, distance_pct, d1_close
        FROM sr_boundary_daily
        WHERE stock_code = ?
        ORDER BY obs_date DESC, boundary_period, boundary_type
        """,
        (stock_code,),
    ).fetchall()

    seen: set[tuple[str, str]] = set()
    records: list[SRRecord] = []
    for r in rows:
        key = (r[1], r[2])
        if key not in seen:
            seen.add(key)
            records.append(
                SRRecord(
                    obs_date=r[0],
                    period=r[1],
                    btype=r[2],
                    boundary_price=float(r[3]),
                    above_r=bool(r[4]),
                    below_s=bool(r[5]),
                    distance_pct=float(r[6]),
                    d1_close=float(r[7]),
                )
            )
    return records


def compute_rr(
    stock_code: str,
    signal: dict,
    close: float,
    sr_records: list[SRRecord],
    signal_date: str,
) -> RREstimate:
    """Compute reward-risk estimate for a single entry signal."""
    est = RREstimate(
        stock_code=stock_code,
        stock_name=signal.get("stock_name", ""),
        strategy_id=signal.get("strategy_id", ""),
        signal_name=signal.get("signal_name", ""),
        signal_date=signal_date,
        current_close=close,
    )

    if not sr_records:
        est.tags.append("无SR数据")
        return est

    # Data staleness
    latest_sr_date = max(r.obs_date for r in sr_records)
    est.sr_data_age_days = (datetime.date.fromisoformat(signal_date) - latest_sr_date).days

    supports = [r for r in sr_records if r.btype == "support"]
    resistances = [r for r in sr_records if r.btype == "resistance"]

    # ------------------------------------------------------------------
    # Downside: nearest support below current price
    # ------------------------------------------------------------------
    valid_supports = [s for s in supports if s.boundary_price < close * 0.999]
    if valid_supports:
        best = min(valid_supports, key=lambda s: (close - s.boundary_price) / close)
        est.downside_pct = (close - best.boundary_price) / close
        est.nearest_support = best.boundary_price
        est.support_period = best.period
        est.downside_method = f"{best.period}_support"
    else:
        est.downside_pct = None
        est.tags.append("无有效支撑")

    # ------------------------------------------------------------------
    # Upside: resistance-based target with breakout mode
    # ------------------------------------------------------------------
    # Sort all resistances by price for breakout mode
    sorted_resistances = sorted(resistances, key=lambda r: r.boundary_price)
    valid_resistances = [r for r in resistances if r.boundary_price > close * 1.001]

    # Breakout mode detection
    is_breakout = "breakout" in signal.get("signal_name", "").lower()
    has_broken = any(r.boundary_price <= close * 1.001 for r in resistances)

    if is_breakout and has_broken:
        # Breakout mode: target the NEXT resistance after the broken one
        next_resistances = [r for r in sorted_resistances if r.boundary_price > close * 1.001]
        if next_resistances:
            nxt = next_resistances[0]
            est.upside_pct = (nxt.boundary_price - close) / close
            est.nearest_resistance = nxt.boundary_price
            est.resistance_period = nxt.period
            est.upside_method = f"{nxt.period}_next_resistance"
            est.tags.append("突破模式_下一阻力")
        else:
            # All resistances broken → channel projection
            if resistances and valid_supports:
                broken = max(resistances, key=lambda r: r.boundary_price)
                same_period_supports = [s for s in valid_supports if s.period == broken.period]
                if same_period_supports:
                    sp = max(same_period_supports, key=lambda s: s.boundary_price)
                    channel = broken.boundary_price - sp.boundary_price
                    est.upside_pct = max(0.0, channel) / close
                    est.broken_resistance = broken.boundary_price
                    est.upside_method = f"channel_projection({broken.period})"
                else:
                    sp = min(valid_supports, key=lambda s: (close - s.boundary_price) / close)
                    channel = broken.boundary_price - sp.boundary_price
                    est.upside_pct = max(0.0, channel) / close
                    est.broken_resistance = broken.boundary_price
                    est.upside_method = "cross_period_channel"
            elif resistances:
                broken = max(resistances, key=lambda r: r.boundary_price)
                breakout = (close - broken.boundary_price) / close
                est.upside_pct = max(0.05, breakout * 2.0)
                est.broken_resistance = broken.boundary_price
                est.upside_method = "breakout_proxy"
                est.tags.append("无有效支撑_突破代理")
            else:
                est.upside_pct = 0.05
                est.upside_method = "default"
                est.tags.append("无阻力数据")
    elif valid_resistances:
        # Normal mode: nearest resistance as target
        best = min(valid_resistances, key=lambda r: (r.boundary_price - close) / close)
        est.upside_pct = (best.boundary_price - close) / close
        est.nearest_resistance = best.boundary_price
        est.resistance_period = best.period
        est.upside_method = f"{best.period}_resistance"
    else:
        # All resistances broken (non-breakout signal, rare)
        if resistances and valid_supports:
            broken = max(resistances, key=lambda r: r.boundary_price)
            same_period_supports = [s for s in valid_supports if s.period == broken.period]
            if same_period_supports:
                sp = max(same_period_supports, key=lambda s: s.boundary_price)
                channel = broken.boundary_price - sp.boundary_price
                est.upside_pct = max(0.0, channel) / close
                est.broken_resistance = broken.boundary_price
                est.upside_method = f"channel_projection({broken.period})"
            else:
                sp = min(valid_supports, key=lambda s: (close - s.boundary_price) / close)
                channel = broken.boundary_price - sp.boundary_price
                est.upside_pct = max(0.0, channel) / close
                est.broken_resistance = broken.boundary_price
                est.upside_method = "cross_period_channel"
        elif resistances:
            broken = max(resistances, key=lambda r: r.boundary_price)
            breakout = (close - broken.boundary_price) / close
            est.upside_pct = max(0.03, breakout * 2.0)
            est.broken_resistance = broken.boundary_price
            est.upside_method = "breakout_proxy"
            est.tags.append("无有效支撑_突破代理")
        else:
            est.upside_pct = 0.03
            est.upside_method = "default"
            est.tags.append("无阻力数据")

    # ------------------------------------------------------------------
    # RR ratio
    # ------------------------------------------------------------------
    if est.upside_pct is not None and est.downside_pct is not None and est.downside_pct > 0:
        est.rr_ratio = est.upside_pct / est.downside_pct

    # ------------------------------------------------------------------
    # Trend strength boost to upside
    # ------------------------------------------------------------------
    ef_count = signal.get("ef_count", 0) or 0
    if ef_count >= 3 and est.upside_pct:
        est.upside_pct *= 1.3
        est.tags.append("三周期共振加成30%")
    elif ef_count == 2 and est.upside_pct:
        est.upside_pct *= 1.15
        est.tags.append("双周期共振加成15%")

    # Recompute RR after upside boost
    if est.upside_pct is not None and est.downside_pct is not None and est.downside_pct > 0:
        est.rr_ratio = est.upside_pct / est.downside_pct

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------
    conf = 0.5
    if "next_resistance" in est.upside_method:
        conf += 0.35  # breakout mode: higher confidence
    elif "resistance" in est.upside_method:
        conf += 0.3
    elif "channel" in est.upside_method:
        conf += 0.1
    elif "breakout" in est.upside_method or "default" in est.upside_method:
        conf -= 0.2

    if est.support_period == "d1":
        conf += 0.1
    elif est.support_period == "w1":
        conf += 0.15
    elif est.support_period == "mn1":
        conf += 0.2

    if est.sr_data_age_days > 30:
        conf -= 0.15
    if est.sr_data_age_days > 60:
        conf -= 0.15

    est.confidence = max(0.0, min(1.0, conf))

    # ------------------------------------------------------------------
    # High-value flag — REMOVED
    # 原因：阻力位止盈违背"让利润奔跑"原则，RR 不再作为决策依据
    # ------------------------------------------------------------------
    # if est.rr_ratio is not None and est.rr_ratio >= 3.0 and est.confidence >= 0.3:
    #     est.high_value = True
    #     est.tags.append("高性价比机会")
    est.high_value = False

    return est


def build_report(estimates: list[RREstimate]) -> dict:
    """Build JSON report."""
    total = len(estimates)
    computable = [e for e in estimates if e.rr_ratio is not None]
    high_value = [e for e in estimates if e.high_value]

    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "signal_date": estimates[0].signal_date if estimates else None,
        "total_signals": total,
        "computable_rr": len(computable),
        "high_value_count": len(high_value),
        "research_only": True,
        "summary": {
            "avg_rr": round(sum(e.rr_ratio for e in computable) / len(computable), 2) if computable else None,
            "max_rr": round(max(e.rr_ratio for e in computable), 2) if computable else None,
            "median_rr": round(sorted(e.rr_ratio for e in computable)[len(computable) // 2], 2) if computable else None,
            "by_close_source": {
                src: len([e for e in estimates if e.close_source == src])
                for src in set(e.close_source for e in estimates)
            },
        },
        "high_value_signals": [
            {
                "stock_code": e.stock_code,
                "stock_name": e.stock_name,
                "strategy": e.strategy_id,
                "signal_name": e.signal_name,
                "rr_ratio": round(e.rr_ratio, 2) if e.rr_ratio else None,
                "upside_pct": round(e.upside_pct * 100, 2) if e.upside_pct else None,
                "downside_pct": round(e.downside_pct * 100, 2) if e.downside_pct else None,
                "confidence": round(e.confidence, 2),
                "nearest_support": e.nearest_support,
                "nearest_resistance": e.nearest_resistance,
                "upside_method": e.upside_method,
                "downside_method": e.downside_method,
            }
            for e in high_value
        ],
        "rows": [
            {
                "stock_code": e.stock_code,
                "stock_name": e.stock_name,
                "strategy_id": e.strategy_id,
                "signal_name": e.signal_name,
                "current_close": e.current_close,
                "close_source": e.close_source,
                "close_date": e.close_date,
                "upside_pct": round(e.upside_pct * 100, 2) if e.upside_pct else None,
                "downside_pct": round(e.downside_pct * 100, 2) if e.downside_pct else None,
                "rr_ratio": round(e.rr_ratio, 2) if e.rr_ratio else None,
                "confidence": round(e.confidence, 2),
                "upside_method": e.upside_method,
                "downside_method": e.downside_method,
                "nearest_support": e.nearest_support,
                "nearest_resistance": e.nearest_resistance,
                "support_period": e.support_period,
                "resistance_period": e.resistance_period,
                "sr_data_age_days": e.sr_data_age_days,
                "high_value": e.high_value,
                "tags": e.tags,
            }
            for e in estimates
        ],
    }


def generate_html(report: dict) -> str:
    rows = report.get("rows", [])
    hv = report.get("high_value_signals", [])

    def row_html(r: dict) -> str:
        cls = "high-value" if r.get("high_value") else ""
        rr = r.get("rr_ratio")
        rr_str = f"{rr:.2f}" if rr is not None else "N/A"
        close_info = f"{r['current_close']}"
        if r.get("close_date") and r.get("close_date") != report.get("signal_date"):
            close_info += f'<br><small style="color:#999">{r["close_date"]} ({r.get("close_source","")})</small>'
        return (
            f'<tr class="{cls}">'
            f'<td>{r["stock_code"]}</td>'
            f'<td>{r["stock_name"]}</td>'
            f'<td>{r["strategy_id"]}</td>'
            f'<td>{r["signal_name"]}</td>'
            f'<td>{close_info}</td>'
            f'<td>{r.get("upside_pct")}</td>'
            f'<td>{r.get("downside_pct")}</td>'
            f'<td><b>{rr_str}</b></td>'
            f'<td>{r["confidence"]}</td>'
            f'<td>{r["upside_method"]}</td>'
            f'<td>{r["downside_method"]}</td>'
            f'<td>{" ".join(r.get("tags", []))}</td>'
            f"</tr>"
        )

    hv_rows = "".join(row_html(r) for r in rows if r.get("high_value"))
    all_rows = "".join(row_html(r) for r in rows)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Reward-Risk Estimation — {report.get("signal_date")}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; font-size: 13px; }}
th {{ background: #f5f5f5; }}
tr.high-value {{ background: #e8f5e9; }}
tr.high-value td {{ font-weight: bold; }}
h2 {{ margin-top: 2rem; }}
.summary {{ background: #fafafa; padding: 1rem; border-radius: 6px; }}
</style>
</head>
<body>
<h1>预估盈亏比分析 — {report.get("signal_date")}</h1>
<div class="summary">
<p>总信号数: <b>{report["total_signals"]}</b> | 可计算 RR: <b>{report["computable_rr"]}</b> | 高性价比机会: <b>{report["high_value_count"]}</b></p>
<p>平均 RR: {report["summary"]["avg_rr"]} | 中位数 RR: {report["summary"]["median_rr"]} | 最大 RR: {report["summary"]["max_rr"]}</p>
</div>

<h2>🎯 高性价比机会 (RR ≥ 3)</h2>
<table>
<tr><th>代码</th><th>名称</th><th>策略</th><th>信号</th><th>收盘价</th><th>Upside%</th><th>Downside%</th><th>RR</th><th>置信度</th><th>Upside方法</th><th>Downside方法</th><th>标签</th></tr>
{hv_rows if hv_rows else '<tr><td colspan="12" style="text-align:center;color:#999">暂无</td></tr>'}
</table>

<h2>全部信号</h2>
<table>
<tr><th>代码</th><th>名称</th><th>策略</th><th>信号</th><th>收盘价</th><th>Upside%</th><th>Downside%</th><th>RR</th><th>置信度</th><th>Upside方法</th><th>Downside方法</th><th>标签</th></tr>
{all_rows}
</table>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Estimate reward-risk for entry signals")
    parser.add_argument("--date", default="2026-05-22", help="Signal date (YYYY-MM-DD)")
    parser.add_argument("--db", type=Path, default=STATE_CACHE_DB, help="Path to state_cache.duckdb")
    args = parser.parse_args()

    signals = load_signals(args.date)
    if not signals:
        print(f"No entry signals found for {args.date}")
        return

    con = duckdb.connect(str(args.db))
    estimates: list[RREstimate] = []

    for sig in signals:
        code = sig.get("stock_code")
        close, close_src, close_dt = get_current_close(con, code, args.date)
        if close is None:
            print(f"  ⚠️ No close data for {code}, skipping")
            continue
        sr = get_latest_sr(con, code)
        est = compute_rr(code, sig, close, sr, args.date)
        est.close_source = close_src
        est.close_date = close_dt.isoformat() if close_dt else None

        if close_dt and args.date:
            sig_dt = datetime.date.fromisoformat(args.date)
            close_age = (sig_dt - close_dt).days
            if close_age > 7:
                est.tags.append(f"收盘价滞后{close_age}天")
                est.confidence = max(0.0, est.confidence - 0.2)

        estimates.append(est)

    con.close()

    report = build_report(estimates)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"reward_risk_{args.date}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    html_path = OUTPUT_DIR / f"reward_risk_{args.date}.html"
    html_path.write_text(generate_html(report), encoding="utf-8")

    print(f"✅ Processed {len(estimates)} signals (research-only, no decision use)")
    print(f"   ⚠️  本输出已降级为只读分析，不做入场/出场决策依据")
    print(f"   JSON: {json_path}")
    print(f"   HTML: {html_path}")


if __name__ == "__main__":
    main()
