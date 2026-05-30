"""Market trend filter.

基于大盘指数判断市场环境, 在熊市降低推荐频率。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketTrend:
    """大盘趋势判断."""

    trend: str          # 'bull', 'bear', 'neutral'
    strength: float     # 0-1
    allow_new_entries: bool
    max_exposure_pct: float  # 建议最大仓位
    min_ef_required: int     # 最低 EF 要求
    message: str


def judge_market_trend(
    index_close: float,
    index_ma20: float,
    index_ma60: float,
    index_adx: float = 0,
    index_plus_di: float = 0,
    index_minus_di: float = 0,
) -> MarketTrend:
    """判断大盘趋势.

    使用沪深300或上证指数的均线和 ADX:
    - 价格 > MA20 > MA60 + ADX>25 = 强牛
    - 价格 > MA20 且 > MA60 = 弱牛
    - 价格 < MA20 < MA60 + ADX>25 = 强熊
    - 其他 = 中性
    """
    above_ma20 = index_close > index_ma20
    above_ma60 = index_close > index_ma60
    ma20_above_ma60 = index_ma20 > index_ma60

    # 强牛
    if above_ma20 and above_ma60 and ma20_above_ma60:
        if index_adx >= 25 and index_plus_di > index_minus_di:
            return MarketTrend(
                trend='bull', strength=0.9,
                allow_new_entries=True, max_exposure_pct=0.8,
                min_ef_required=2,
                message='强牛市, 积极参与'
            )
        return MarketTrend(
            trend='bull', strength=0.6,
            allow_new_entries=True, max_exposure_pct=0.7,
            min_ef_required=2,
            message='温和牛市, 正常参与'
        )

    # 强熊
    if not above_ma20 and not above_ma60 and not ma20_above_ma60:
        if index_adx >= 25 and index_minus_di > index_plus_di:
            return MarketTrend(
                trend='bear', strength=0.9,
                allow_new_entries=False, max_exposure_pct=0.2,
                min_ef_required=3,
                message='强熊市, 建议观望'
            )
        return MarketTrend(
            trend='bear', strength=0.5,
            allow_new_entries=True, max_exposure_pct=0.4,
            min_ef_required=3,
            message='弱熊市, 仅参与最强信号'
        )

    # 中性
    return MarketTrend(
        trend='neutral', strength=0.4,
        allow_new_entries=True, max_exposure_pct=0.6,
        min_ef_required=2,
        message='震荡市, 精选信号'
    )


def filter_by_market_trend(
    signals: list[dict],
    market: MarketTrend,
) -> list[dict]:
    """根据大盘趋势过滤信号.

    熊市只保留 EF 3/3 的超强信号。
    中性市场加权 quality_score。
    """
    if not market.allow_new_entries:
        return []

    filtered = []
    for s in signals:
        ef = s.get('ef_count', 0)
        if ef < market.min_ef_required:
            continue

        # 熊市加分: 只有最强信号才能通过
        if market.trend == 'bear' and ef < 3:
            continue

        # 加入市场趋势权重
        market_weight = market.strength
        s['adjusted_score'] = s.get('quality_score', 50) * (0.7 + 0.3 * market_weight)
        filtered.append(s)

    return sorted(filtered, key=lambda x: x.get('adjusted_score', 0), reverse=True)
