"""Composite quality score for E/F signals.

将多个维度的信号强度综合为一个 0-100 的质量分。
分数越高, 信号越可靠。

维度:
1. State 强度 (EF 周期数 + 各周期 state score)
2. 趋势一致性 (三周期趋势方向是否一致)
3. 突破质量 (位置位是否为上突)
4. 波动率健康度 (是否在合理扩张区间)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityBreakdown:
    """质量分各维度明细."""

    state_strength: float     # 0-30
    trend_alignment: float    # 0-25
    breakout_quality: float   # 0-25
    volatility_health: float  # 0-20
    total: float              # 0-100
    grade: str                # S/A/B/C

    def to_dict(self) -> dict:
        return {
            'state_strength': round(self.state_strength, 1),
            'trend_alignment': round(self.trend_alignment, 1),
            'breakout_quality': round(self.breakout_quality, 1),
            'volatility_health': round(self.volatility_health, 1),
            'total': round(self.total, 1),
            'grade': self.grade,
        }


def score_state_strength(state: dict) -> float:
    """State 强度评分 (0-30).

    - EF 周期数: 2/3 = 15, 3/3 = 25
    - 各周期 state score 累加 (最高 +5)
    """
    ef_count = state.get('ef_count', 0)
    if ef_count < 2:
        return 0.0

    base = 15.0 if ef_count == 2 else 25.0

    # state score bonus (各周期越接近 15 越好)
    scores = [
        abs(state.get('mn1_state_score', 0)),
        abs(state.get('w1_state_score', 0)),
        abs(state.get('d1_state_score', 0)),
    ]
    avg_score = sum(scores) / 3
    bonus = min(avg_score / 15 * 5, 5.0)

    return min(base + bonus, 30.0)


def score_trend_alignment(state: dict) -> float:
    """趋势一致性评分 (0-25).

    - 三周期趋势方向一致 (全牛) = 25
    - 两周期一致 = 15
    - 趋势分散 = 5
    """
    # 从 trend_bit 判断 (1 = 有趋势)
    trends = []
    for prefix in ['mn1', 'w1', 'd1']:
        trend_bit = state.get(f'{prefix}_trend_bit', 0)
        trend_label = state.get(f'{prefix}_trend_label', '')
        # 牛市 = +1, 熊市 = -1, 中性 = 0
        if '牛' in str(trend_label) or (trend_bit == 1 and state.get(f'{prefix}_state_score', 0) > 0):
            trends.append(1)
        elif '熊' in str(trend_label) or (trend_bit == 1 and state.get(f'{prefix}_state_score', 0) < 0):
            trends.append(-1)
        else:
            trends.append(0)

    # 全部牛
    if all(t == 1 for t in trends):
        return 25.0
    # 两个牛
    if trends.count(1) >= 2:
        return 18.0
    # 一个牛
    if trends.count(1) >= 1:
        return 10.0
    # 有熊
    if any(t == -1 for t in trends):
        return 2.0
    return 5.0


def score_breakout_quality(state: dict) -> float:
    """突破质量评分 (0-25).

    - position_bit = 1 (上突) 的周期数越多越好
    - D1 上突权重最高
    """
    score = 0.0
    for prefix, weight in [('mn1', 5), ('w1', 8), ('d1', 12)]:
        pos_bit = state.get(f'{prefix}_position_bit', 0)
        if pos_bit == 1:  # 上突
            score += weight
        elif pos_bit == 2:  # 也视为上突 (不同编码)
            score += weight

    return min(score, 25.0)


def score_volatility_health(state: dict) -> float:
    """波动率健康度评分 (0-20).

    - volatility_bit = 1 (波扩) = 好事, 但太多周期波扩可能是过热
    - 最佳: D1 波扩, W1 稳, MN1 稳 (有序扩张)
    - 最差: 全部波扩 (可能过热)
    """
    vol_bits = []
    for prefix in ['mn1', 'w1', 'd1']:
        vol_bits.append(state.get(f'{prefix}_volatility_bit', 0))

    expanding_count = sum(vol_bits)

    if expanding_count == 0:
        return 8.0    # 全稳, 一般
    elif expanding_count == 1:
        # D1 波扩最佳
        if vol_bits[2] == 1:
            return 18.0
        return 14.0
    elif expanding_count == 2:
        return 16.0   # 适度扩张
    else:
        return 10.0   # 全波扩, 可能过热


def calc_quality_score(state: dict) -> QualityBreakdown:
    """计算综合质量分.

    Args:
        state: 包含 state 信息的 dict, 需要以下字段:
            - ef_count, mn1/w1/d1_state_score
            - mn1/w1/d1_trend_bit, mn1/w1/d1_trend_label
            - mn1/w1/d1_position_bit
            - mn1/w1/d1_volatility_bit
    """
    s1 = score_state_strength(state)
    s2 = score_trend_alignment(state)
    s3 = score_breakout_quality(state)
    s4 = score_volatility_health(state)
    total = s1 + s2 + s3 + s4

    if total >= 85:
        grade = 'S'
    elif total >= 70:
        grade = 'A'
    elif total >= 50:
        grade = 'B'
    else:
        grade = 'C'

    return QualityBreakdown(
        state_strength=s1,
        trend_alignment=s2,
        breakout_quality=s3,
        volatility_health=s4,
        total=total,
        grade=grade,
    )


def rank_by_quality(states: list[dict]) -> list[dict]:
    """按质量分排序, 在每个 state dict 中添加 quality 字段."""
    for s in states:
        q = calc_quality_score(s)
        s['quality_score'] = q.total
        s['quality_grade'] = q.grade
        s['quality_breakdown'] = q.to_dict()
    return sorted(states, key=lambda x: x['quality_score'], reverse=True)
