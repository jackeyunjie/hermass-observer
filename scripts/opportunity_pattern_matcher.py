#!/usr/bin/env python3
"""机会模式匹配工具 — 跨模块共享。

被 strategy_signal_ledger / strategy_reminder_brief / daily_research_brief 共同调用。

职责：
  1. 加载注册表 config/opportunity_pattern_registry.json
  2. 计算 W1/MN1 压缩编码
  3. 匹配信号 → 已验证模式
  4. 计算 pattern_boost 加成系数
  5. 判断四维共振
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "opportunity_pattern_registry.json"
DAILY_JSON_PATH = ROOT / "outputs" / "project" / "opportunity_patterns_daily.json"

W1_COMPRESS = {0: "con_f", 1: "con_f", 2: "con_f", 3: "con_f",
               4: "con_t", 5: "con_t", 6: "con_t", 7: "con_t",
               8: "exp_f", 9: "exp_f", 10: "exp_f", 11: "exp_f",
               12: "exp_t", 13: "exp_t", 14: "exp_t", 15: "exp_t"}

MN1_COMPRESS = {0: "con_f", 1: "con_f", 2: "con_f", 3: "con_f",
                4: "con_t", 5: "con_t", 6: "con_t", 7: "con_t",
                8: "exp_f", 9: "exp_f", 10: "exp_f", 11: "exp_f",
                12: "exp_t", 13: "exp_t", 14: "exp_t", 15: "exp_t"}


def _compress(mapping: dict[int, str], score: int) -> str:
    return mapping.get(score, str(score))


def encode_pattern(d1_from_hex: str, d1_to_hex: str,
                   w1_score: int, mn1_score: int) -> str:
    return (f"D{d1_from_hex}_{d1_to_hex}"
            f"_W{_compress(W1_COMPRESS, w1_score)}"
            f"_M{_compress(MN1_COMPRESS, mn1_score)}")


def load_registry() -> dict[str, Any]:
    """加载模式注册表。优先读 Kimi 脚本产出的 daily JSON（list），
    自动转换为 dict 索引；其次读旧版 dict 注册表。"""
    # 优先读新版 Kimi daily JSON
    if DAILY_JSON_PATH.exists():
        daily = json.loads(DAILY_JSON_PATH.read_text(encoding="utf-8"))
        patterns_list = daily.get("patterns")
        if isinstance(patterns_list, list) and patterns_list:
            patterns_dict = {}
            for p in patterns_list:
                code = p.get("pattern_code")
                if not code:
                    continue
                ci = [p.get("mean_excess_ci_lo"), p.get("mean_excess_ci_hi")]
                patterns_dict[code] = {
                    "pattern_key": code,
                    "status": p.get("status", "pending"),
                    "n": p.get("n", 0),
                    "mean_excess": p.get("mean_excess"),
                    "ci_95": [ci[0] if ci[0] is not None else 0,
                              ci[1] if ci[1] is not None else 0],
                    "win_rate": p.get("win_rate"),
                    "from_state": p.get("d1_from_hex", ""),
                    "to_state": p.get("d1_to_hex", ""),
                    "pattern_boost": 0.0,
                }
            return {"patterns": patterns_dict}

    # 其次读旧版 dict 注册表
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    return {"patterns": {}}


def get_verified_patterns() -> dict[str, dict[str, Any]]:
    reg = load_registry()
    return {k: v for k, v in reg.get("patterns", {}).items()
            if v.get("status") == "verified"}


def compute_pattern_boost(pattern: dict) -> float:
    ci = pattern.get("ci_95", [0, 0])
    ci_lo = ci[0] if len(ci) > 0 else 0
    ci_hi = ci[1] if len(ci) > 1 else 0
    ci_width = abs(ci_hi - ci_lo) if ci_hi and ci_lo else 0.10
    ci_tightness = max(0, 1.0 - ci_width / 0.10)
    n = pattern.get("n", 0)
    wr = pattern.get("win_rate", 0)
    n_factor = min(1.0, n / 500)
    wr_factor = max(0, (wr - 0.5) * 2)
    raw = 0.05 + ci_tightness * 0.05 + n_factor * 0.03 + wr_factor * 0.02
    return round(min(0.15, max(0.0, raw)), 3)


def match_signal_to_pattern(
    d1_from_hex: str,
    d1_to_hex: str,
    w1_score: int,
    mn1_score: int,
) -> dict[str, Any] | None:
    """匹配策略信号到已验证模式。

    参数：
        d1_from_hex：昨日 D1 hex（如 '4', 'C', '-E'）
        d1_to_hex：今日 D1 hex
        w1_score：今日 W1 得分
        mn1_score：今日 MN1 得分

    返回：
        匹配的模式信息 dict，含 pattern_key, boost, mean_excess 等；None 表示未命中
    """
    verified = get_verified_patterns()
    if not verified:
        return None

    pkey = encode_pattern(d1_from_hex, d1_to_hex, w1_score, mn1_score)
    pattern = verified.get(pkey)
    if not pattern:
        return None

    boost = compute_pattern_boost(pattern)
    ci = pattern.get("ci_95", [0, 0])

    return {
        "pattern_key": pkey,
        "pattern_status": "verified",
        "pattern_description": f"D1从{pattern.get('from_state','')}跃迁至{pattern.get('to_state','')}",
        "pattern_mean_excess": pattern.get("mean_excess", 0),
        "pattern_ci_lo": ci[0] if len(ci) > 0 else 0,
        "pattern_ci_hi": ci[1] if len(ci) > 1 else 0,
        "pattern_n": pattern.get("n", 0),
        "pattern_win_rate": pattern.get("win_rate", 0),
        "pattern_boost": boost,
    }


def identify_highest_conviction(
    macro_dir: str,
    chain_dir: str,
    state_dir: str,
    pattern_match: dict | None,
) -> dict[str, Any]:
    """四维共振判断。"""
    all_positive = (
        macro_dir == "positive"
        and chain_dir == "positive"
        and state_dir == "positive"
        and pattern_match is not None
    )
    if all_positive:
        return {
            "conviction_level": "highest",
            "conviction_label": "★ 四维共振",
            "dimensions": {
                "macro": "positive",
                "chain": "positive",
                "state": "positive",
                "pattern": pattern_match["pattern_key"],
            },
        }
    return {"conviction_level": "normal", "conviction_label": ""}


if __name__ == "__main__":
    verified = get_verified_patterns()
    print(f"Verified patterns: {len(verified)}")
    for k, v in list(verified.items())[:3]:
        print(f"  {k}: n={v.get('n')}, excess={v.get('mean_excess'):.4f}, boost={compute_pattern_boost(v):.3f}")
