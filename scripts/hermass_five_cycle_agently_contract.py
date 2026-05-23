#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


通用周期 = ["MN1", "W1", "D1", "H4", "H1"]
通用行数 = {"MN1": 12, "W1": 12, "D1": 36, "H4": 36, "H1": 120}
通用列 = {
    "MN1": ["MN1"],
    "W1": ["MN1", "W1"],
    "D1": ["MN1", "W1", "D1"],
    "H4": ["MN1", "W1", "D1", "H4"],
    "H1": ["MN1", "W1", "D1", "H4", "H1"],
}


通用规则 = {
    "公式": "底座只能在 0 和 8 中二选一；状态分数绝对值=底座+波动位一+位置位二+趋势位四；状态码=带方向的大写十六进制状态分数",
    "观察态": "观察周期收盘价替换被观察周期当前收盘价后重新计算位置和状态码",
    "禁止": "禁止直接复制被观察周期原状态码作为跨周期状态",
    "适用范围": "所有品种、所有五周期视角表",
}


def 计算视角状态(观察行: dict[str, Any], 被观察周期: str, 被观察周期序列: list[dict[str, Any]], 被观察序号: int, ea: Any, pd: Any) -> dict[str, Any]:
    被观察行 = 被观察周期序列[被观察序号]
    原审计 = 被观察行["audit"]
    组件 = dict(原审计["components"])

    观察收盘价 = float(观察行["close"])
    历史窗口 = 被观察周期序列[: 被观察序号 + 1]

    收盘序列 = [float(row["close"]) for row in 历史窗口]
    收盘序列[-1] = 观察收盘价
    支撑序列 = [row["audit"]["indicators"].get("support") for row in 历史窗口]
    压力序列 = [row["audit"]["indicators"].get("resistance") for row in 历史窗口]

    位置 = ea.classify_position(
        pd.Series(收盘序列),
        pd.Series(支撑序列, dtype="float64"),
        pd.Series(压力序列, dtype="float64"),
    )
    分数 = ea.calc_state_score(
        组件.get("compression") or "neutral",
        组件.get("trend") or "neutral",
        位置,
        组件.get("volatility") or "neutral",
    )

    组件["position"] = 位置
    组件["state_score"] = 分数
    组件["state_hex"] = ea.to_signed_hex(分数)
    return 组件


def 计算视角状态审计(
    观察行: dict[str, Any],
    被观察周期: str,
    被观察周期序列: list[dict[str, Any]],
    被观察序号: int,
    ea: Any,
    pd: Any,
    decode_state: Any,
    clean_value: Any,
) -> dict[str, Any]:
    被观察行 = 被观察周期序列[被观察序号]
    原审计 = 被观察行["audit"]
    指标 = dict(原审计["indicators"])
    组件 = 计算视角状态(观察行, 被观察周期, 被观察周期序列, 被观察序号, ea, pd)
    观察收盘价 = float(观察行["close"])
    分数 = 组件["state_score"]

    指标["observing_close"] = clean_value(观察收盘价)
    指标["native_close"] = clean_value(被观察行["close"])
    指标["observed_timeframe"] = 被观察周期
    指标["observed_time"] = 被观察行["close_at"].isoformat(sep=" ")

    return {
        **原审计,
        "timeframe": 被观察周期,
        "time": 被观察行["close_at"].isoformat(sep=" "),
        "observation": {
            "mode": "视角收盘价观察被观察周期关键位",
            "observing_timeframe": 观察行["timeframe"],
            "observing_time": 观察行["close_at"].isoformat(sep=" "),
            "observing_close": clean_value(观察收盘价),
            "observed_timeframe": 被观察周期,
            "observed_time": 被观察行["close_at"].isoformat(sep=" "),
            "native_close": clean_value(被观察行["close"]),
            "native_state_hex": 原审计["components"].get("state_hex"),
        },
        "components": {key: clean_value(value) for key, value in 组件.items()},
        "bits": decode_state(分数),
        "indicators": 指标,
    }


def 校验五周期结果(payload: dict[str, Any], 期望行数: dict[str, int] | None = None) -> dict[str, Any]:
    行数规则 = 期望行数 or 通用行数
    错误 = []
    for 视角, 行数 in 行数规则.items():
        rows = payload["views"][视角]
        audits = payload["row_audit"][视角]
        if len(rows) != 行数:
            错误.append(f"{视角} 行数 {len(rows)} != {行数}")
        for idx, row in enumerate(rows):
            audit = audits[idx]
            for 周期 in 通用列[视角]:
                左侧 = row[f"{周期}state"]
                item = audit["states"][周期]
                右侧 = item["components"]["state_hex"]
                观察 = item.get("observation", {})
                if 左侧 != 右侧:
                    错误.append(f"{视角} 第 {idx + 1} 行 {周期} 左侧 {左侧} != 右侧 {右侧}")
                if 观察.get("observing_timeframe") != 视角:
                    错误.append(f"{视角} 第 {idx + 1} 行 {周期} 观察周期错误")
                if 观察.get("observed_timeframe") != 周期:
                    错误.append(f"{视角} 第 {idx + 1} 行 {周期} 被观察周期错误")
                if 观察.get("observing_close") is None:
                    错误.append(f"{视角} 第 {idx + 1} 行 {周期} 缺观察收盘价")
                if 周期 != 视角 and item["components"]["state_hex"] == "":
                    错误.append(f"{视角} 第 {idx + 1} 行 {周期} 跨周期状态为空")
    if 错误:
        raise RuntimeError("；".join(错误[:20]))
    return {
        "错误数": 0,
        "行数": {周期: len(payload["views"][周期]) for 周期 in 通用周期},
        "规则": 通用规则,
    }
