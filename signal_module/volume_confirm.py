"""Volume confirmation signals.

突破信号的成交量确认。
量价齐升 = 信号可靠。
缩量突破 = 可能是假突破。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VolumeSignal:
    """量能信号."""

    confirmed: bool       # 是否放量确认
    volume_ratio: float   # 量比 (当日量 / 均量)
    volume_trend: str     # 'expanding', 'contracting', 'normal'
    score: float          # 0-10 加分
    message: str


def calc_volume_ratio(
    current_volume: float,
    avg_volume_20d: float,
) -> float:
    """计算量比 (当日成交量 / 20日均量)."""
    if avg_volume_20d <= 0:
        return 1.0
    return current_volume / avg_volume_20d


def check_volume_confirm(
    current_volume: float,
    avg_volume_20d: float,
    volume_5d_avg: float = 0,
    threshold: float = 1.5,
) -> VolumeSignal:
    """检查成交量是否确认突破.

    Args:
        current_volume: 当日成交量
        avg_volume_20d: 20日均量
        volume_5d_avg: 5日均量 (用于判断趋势)
        threshold: 量比阈值 (默认 1.5 倍)

    Returns:
        VolumeSignal
    """
    vr = calc_volume_ratio(current_volume, avg_volume_20d)

    # 量能趋势
    if volume_5d_avg > 0 and avg_volume_20d > 0:
        trend_ratio = volume_5d_avg / avg_volume_20d
        if trend_ratio > 1.2:
            trend = 'expanding'
        elif trend_ratio < 0.8:
            trend = 'contracting'
        else:
            trend = 'normal'
    else:
        trend = 'unknown'

    # 评分
    confirmed = vr >= threshold
    if vr >= 2.0:
        score = 10.0
        msg = f"大幅放量 (量比 {vr:.1f})"
    elif vr >= threshold:
        score = 7.0
        msg = f"放量确认 (量比 {vr:.1f})"
    elif vr >= 1.0:
        score = 4.0
        msg = f"温和放量 (量比 {vr:.1f})"
    elif vr >= 0.7:
        score = 2.0
        msg = f"缩量 (量比 {vr:.1f}), 突破可靠性降低"
    else:
        score = 0.0
        msg = f"严重缩量 (量比 {vr:.1f}), 可能是假突破"

    return VolumeSignal(
        confirmed=confirmed,
        volume_ratio=round(vr, 2),
        volume_trend=trend,
        score=score,
        message=msg,
    )
