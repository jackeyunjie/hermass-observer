#!/usr/bin/env python3
"""
build_daily_warning.py

基于 2026-05-29 大跌回溯研究的核心发现，每日计算三个预警指标：
1. D1 负值日增量（与昨日对比）
2. MN1 正值占比变化（与昨日对比）
3. 高位正→负突变估算（昨日 ef≥2 → 今日 ef=0 的数量近似）

输出：outputs/daily_warning.json

设计约束：
- 由 run_daily_pipeline.sh 在 Step 7（快照）之后调用一次
- 读取 outputs/daily_snapshot.json 和前一日快照
- 不阻塞当前运行中的 Agent
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 配置 ──
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SNAPSHOT_PATH = PROJECT_ROOT / "outputs" / "daily_snapshot.json"
SNAPSHOT_ARCHIVE_DIR = PROJECT_ROOT / "outputs" / "daily_snapshot"
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "daily_warning.json"

# 回溯验证阈值（基于 5/29 研究）
THRESHOLDS = {
    "d1_negative_yellow": 200,  # 黄色警戒：D1 负值日增 > 200 只
    "d1_negative_orange": 500,  # 橙色警戒：D1 负值日增 > 500 只
    "high_to_negative_red": 400,  # 红色警戒：高位正→负突变 > 400 只
    "mn1_positive_red": -1.0,  # 红色警戒：MN1 正值占比 -1pct 以上
    "breather_trap_ef2_delta": 0.5,  # 诱多：ef2 占比环比 +0.5pct 以上
    "breather_trap_mn1_delta": -0.5,  # 诱多：MN1 正值占比仍在下降 -0.5pct 以上
    "breather_trap_d1_neg_delta": 200,  # 诱多：D1 负值仍在增加 +200 只以上
    "all_clear_d1_neg": 150,  # 预警解除：高位正→负突变 < 150 只/日
    "all_clear_mn1_delta": -0.3,  # 预警解除：MN1 环比 ≥ -0.3pct
}


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_prev_snapshot(today_date: str) -> Path | None:
    """
    根据今日日期，在 daily_snapshot 归档目录中查找前一个交易日的快照。
    简单策略：找日期小于 today_date 的最新文件。
    """
    if not SNAPSHOT_ARCHIVE_DIR.exists():
        return None

    today_dt = datetime.strptime(today_date, "%Y-%m-%d").date()
    candidates = []
    for p in SNAPSHOT_ARCHIVE_DIR.glob("daily_snapshot_*.json"):
        fname = p.name
        try:
            # daily_snapshot_20260529.json -> 20260529
            date_str = fname.replace("daily_snapshot_", "").replace(".json", "")
            d = datetime.strptime(date_str, "%Y%m%d").date()
            if d < today_dt:
                candidates.append((d, p))
        except ValueError:
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def compute_metrics(today: dict, yesterday: dict | None) -> dict:
    """计算今日与昨日的三个核心预警指标。"""
    today_stocks = today.get("stocks", [])
    today_total = today["market"]["total"]

    # 今日 D1 负值（sc[2] 是 D1 score，由 5/29 数据验证）
    today_d1_neg = sum(1 for s in today_stocks if s["sc"][2] < 0)
    # 今日 MN1 正值（sc[0] 是 MN1 score）
    today_mn1_pos = sum(1 for s in today_stocks if s["sc"][0] > 0)
    today_mn1_pos_pct = round(100.0 * today_mn1_pos / today_total, 2)
    # 今日 ef2 占比
    today_ef2_pct = today["market"].get("ef2_pct", 0.0)

    metrics = {
        "date": today.get("date", ""),
        "today_total": today_total,
        "today_d1_negative": today_d1_neg,
        "today_mn1_positive_pct": today_mn1_pos_pct,
        "today_ef2_pct": today_ef2_pct,
        "d1_negative_delta": None,
        "mn1_positive_pct_delta": None,
        "ef2_pct_delta": None,
        "high_to_negative_estimate": None,
        "alert_level": "green",
        "breather_trap": False,
        "message": "",
    }

    if yesterday is None:
        metrics["message"] = "无昨日快照，无法计算日环比预警指标。"
        return metrics

    yesterday_stocks = yesterday.get("stocks", [])
    yesterday_total = yesterday["market"]["total"]

    # 1. D1 负值日增量
    yesterday_d1_neg = sum(1 for s in yesterday_stocks if s["sc"][2] < 0)
    d1_neg_delta = today_d1_neg - yesterday_d1_neg
    metrics["d1_negative_delta"] = d1_neg_delta

    # 2. MN1 正值占比变化
    yesterday_mn1_pos = sum(1 for s in yesterday_stocks if s["sc"][0] > 0)
    yesterday_mn1_pos_pct = round(100.0 * yesterday_mn1_pos / yesterday_total, 2)
    mn1_pos_delta = round(today_mn1_pos_pct - yesterday_mn1_pos_pct, 2)
    metrics["mn1_positive_pct_delta"] = mn1_pos_delta

    # ef2 占比变化（用于诱多陷阱检测）
    yesterday_ef2_pct = yesterday["market"].get("ef2_pct", 0.0)
    ef2_pct_delta = round(today_ef2_pct - yesterday_ef2_pct, 2)
    metrics["ef2_pct_delta"] = ef2_pct_delta

    # 3. 高位正→负突变估算
    # 近似：昨日 ef≥2 的股票中，今日 ef=0 的数量
    # 需要按 stock code 匹配
    yesterday_ef_map = {s["c"]: s["ef"] for s in yesterday_stocks}
    high_to_neg = 0
    for s in today_stocks:
        code = s["c"]
        prev_ef = yesterday_ef_map.get(code)
        if prev_ef is not None and prev_ef >= 2 and s["ef"] == 0:
            high_to_neg += 1
    metrics["high_to_negative_estimate"] = high_to_neg

    return metrics


def determine_alert(metrics: dict) -> dict:
    """根据指标判断预警级别和诱多陷阱。"""
    d1_delta = metrics.get("d1_negative_delta")
    mn1_delta = metrics.get("mn1_positive_pct_delta")
    ef2_delta = metrics.get("ef2_pct_delta")
    high_to_neg = metrics.get("high_to_negative_estimate")

    if d1_delta is None:
        return metrics

    # ── 诱多陷阱检测（第 6 条）──
    breather = False
    if (
        ef2_delta is not None
        and ef2_delta >= THRESHOLDS["breather_trap_ef2_delta"]
        and mn1_delta is not None
        and mn1_delta <= THRESHOLDS["breather_trap_mn1_delta"]
        and d1_delta >= THRESHOLDS["breather_trap_d1_neg_delta"]
    ):
        breather = True
        metrics["breather_trap"] = True

    # ── 三级警戒体系（第 7 条）──
    alert = "green"
    messages = []

    if d1_delta > THRESHOLDS["d1_negative_orange"]:
        alert = "orange"
        messages.append(
            f"⚠️ 结构恶化加速：今日 D1 负值暴增 {d1_delta} 只，高位崩跌约 {high_to_neg} 只。建议防御。"
        )
    elif d1_delta > THRESHOLDS["d1_negative_yellow"]:
        alert = "yellow"
        messages.append(f"注意：负值扩散加速（+{d1_delta} 只），建议减仓观察。")

    # 红色警戒：高位崩跌 + MN1 侵蚀
    if (
        high_to_neg is not None
        and high_to_neg > THRESHOLDS["high_to_negative_red"]
        and mn1_delta is not None
        and mn1_delta <= THRESHOLDS["mn1_positive_red"]
    ):
        alert = "red"
        messages.append("🔴 多周期结构同步恶化：月线支撑正在被侵蚀，不是普通回调。强烈建议降低风险暴露。")

    if breather:
        messages.append("⚠️ ef2 反弹但月线结构仍在恶化——当前不是止跌确认，是诱多陷阱。建议防御，不追反弹。")

    metrics["alert_level"] = alert
    metrics["message"] = " ".join(messages) if messages else "市场结构指标正常，无显著预警。"

    return metrics


def main():
    if not SNAPSHOT_PATH.exists():
        print(f"[ERROR] 今日快照不存在: {SNAPSHOT_PATH}", file=sys.stderr)
        sys.exit(1)

    today = load_json(SNAPSHOT_PATH)
    today_date = today.get("date", "")
    if not today_date:
        print("[ERROR] 今日快照缺少 date 字段", file=sys.stderr)
        sys.exit(1)

    prev_path = find_prev_snapshot(today_date)
    yesterday = load_json(prev_path) if prev_path else None

    if yesterday is None:
        print(f"[WARN] 未找到 {today_date} 的前一交易日快照，跳过环比计算。")

    metrics = compute_metrics(today, yesterday)
    metrics = determine_alert(metrics)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"[OK] 预警报告已写入: {OUTPUT_PATH}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
