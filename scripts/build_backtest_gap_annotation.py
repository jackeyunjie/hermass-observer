import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNAL_FILE = ROOT / "outputs" / "strategy_signals" / "strategy_signal_daily_latest.json"
SNAPSHOT_FILE = ROOT / "outputs" / "daily_snapshot.json"


def load_signal_stocks() -> dict:
    """返回 {stock_code: strategy_id} 仅 entry 信号"""
    if not SIGNAL_FILE.exists():
        return {}
    data = json.loads(SIGNAL_FILE.read_text(encoding="utf-8"))
    entries = {}
    for r in data.get("rows", []):
        if r.get("signal_type") == "entry" and r.get("display_scope") != "research":
            entries[r["stock_code"]] = r["strategy_id"]
    return entries


def load_atr_map() -> dict:
    """返回 {stock_code: (price, atr)}"""
    if not SNAPSHOT_FILE.exists():
        return {}
    data = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    atr_map = {}
    for s in data.get("stocks", []):
        code = s.get("c", "")
        price = s.get("p", 0)
        atr = s.get("atr", 0)
        if code and price and atr:
            atr_map[code] = (price, atr)
    return atr_map


def build_backtest_gap_annotation() -> dict:
    entries = load_signal_stocks()
    atr_map = load_atr_map()

    vcp_count = sum(1 for sid, strat in entries.items() if strat == "vcp")
    bollinger_count = sum(1 for sid, strat in entries.items() if strat == "bollinger_bandit")
    total_entry = len(entries)

    atr_pcts = []
    for code in entries:
        if code in atr_map:
            price, atr = atr_map[code]
            if price > 0:
                atr_pcts.append((atr / price) * 100)

    median_atr_pct = round(statistics.median(atr_pcts), 1) if atr_pcts else 0

    return {
        "vcp_entry_count": vcp_count,
        "bollinger_entry_count": bollinger_count,
        "total_entry_count": total_entry,
        "atr_sample_count": len(atr_pcts),
        "median_atr_pct": median_atr_pct,
        "affected_count": total_entry,
        "estimated_gap_pct": median_atr_pct,
        "gap_note": "基于信号标的当日ATR/收盘中位值估算T+1滑点影响（不含涨跌停/停牌极端场景）",
    }


if __name__ == "__main__":
    result = build_backtest_gap_annotation()
    print(json.dumps(result, ensure_ascii=False, indent=2))
