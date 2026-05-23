"""Sector rotation filter.

行业轮动过滤:
- 避免在同一行业过度集中
- 优选当前强势行业
- 行业景气度判断
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SectorInfo:
    """行业信息."""

    code: str       # 行业代码 (申万一级)
    name: str       # 行业名称
    rank: int       # 近期涨幅排名
    momentum: str   # 'strong', 'weak', 'neutral'


@dataclass
class SectorFilterResult:
    """行业过滤结果."""

    allowed: bool
    sector: str
    sector_rank: int
    reason: str
    score_adjustment: float  # 分数调整 (+/-)


def deduplicate_sectors(
    signals: list[dict],
    max_per_sector: int = 3,
) -> list[dict]:
    """行业去重: 每个行业最多保留 N 只.

    按 quality_score 降序排列后, 每行业取 top N。
    """
    sector_count: dict[str, int] = {}
    result = []

    # 已按 score 排序
    for s in signals:
        sector = s.get('sector', 'unknown')
        count = sector_count.get(sector, 0)
        if count < max_per_sector:
            result.append(s)
            sector_count[sector] = count + 1

    return result


def check_sector_momentum(
    sector: str,
    sector_rankings: dict[str, int],
) -> SectorFilterResult:
    """检查行业动量.

    sector_rankings: {sector_name: rank} (rank 1 = 最强)
    """
    rank = sector_rankings.get(sector, 99)

    if rank <= 5:
        return SectorFilterResult(
            allowed=True, sector=sector, sector_rank=rank,
            reason=f"行业 {sector} 排名第 {rank}, 强势行业",
            score_adjustment=10.0,
        )
    elif rank <= 15:
        return SectorFilterResult(
            allowed=True, sector=sector, sector_rank=rank,
            reason=f"行业 {sector} 排名第 {rank}, 中性",
            score_adjustment=0.0,
        )
    else:
        return SectorFilterResult(
            allowed=True, sector=sector, sector_rank=rank,
            reason=f"行业 {sector} 排名第 {rank}, 弱势行业, 建议降低仓位",
            score_adjustment=-5.0,
        )


def apply_sector_filter(
    signals: list[dict],
    sector_rankings: dict[str, int] | None = None,
    max_per_sector: int = 3,
) -> list[dict]:
    """应用行业过滤.

    1. 行业去重
    2. 行业动量加分/减分
    """
    # Step 1: 去重
    deduped = deduplicate_sectors(signals, max_per_sector)

    if not sector_rankings:
        return deduped

    # Step 2: 动量调整
    for s in deduped:
        sector = s.get('sector', 'unknown')
        result = check_sector_momentum(sector, sector_rankings)
        s['sector_filter'] = result.reason
        s['quality_score'] = s.get('quality_score', 50) + result.score_adjustment

    return sorted(deduped, key=lambda x: x.get('quality_score', 0), reverse=True)
