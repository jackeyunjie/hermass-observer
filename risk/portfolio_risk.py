"""Portfolio-level risk management.

组合层面的风控:
- 单只仓位限制
- 行业集中度限制
- 总仓位动态调节
- 相关性检查
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PortfolioRiskCheck:
    """风控检查结果."""

    passed: bool
    violations: list[str]
    warnings: list[str]
    max_allowed_positions: int
    current_positions: int
    sector_concentrations: dict[str, float]
    total_exposure_pct: float


def check_single_position_limit(
    position_value: float,
    total_equity: float,
    max_pct: float = 0.10,
) -> tuple[bool, str]:
    """检查单只仓位是否超限."""
    pct = position_value / total_equity if total_equity > 0 else 0
    if pct > max_pct:
        return False, f"单只仓位 {pct:.1%} 超过限制 {max_pct:.0%}"
    return True, ''


def check_sector_concentration(
    positions: list[dict],
    max_sector_pct: float = 0.30,
) -> tuple[bool, dict[str, float], list[str]]:
    """检查行业集中度.

    positions: [{code, name, value, sector}]
    """
    sector_values: dict[str, float] = {}
    total = sum(p.get('value', 0) for p in positions)
    if total <= 0:
        return True, {}, []

    for p in positions:
        sector = p.get('sector', 'unknown')
        sector_values[sector] = sector_values.get(sector, 0) + p.get('value', 0)

    violations = []
    concentrations = {}
    for sector, value in sector_values.items():
        pct = value / total
        concentrations[sector] = round(pct, 4)
        if pct > max_sector_pct:
            violations.append(f"行业 {sector} 占比 {pct:.1%} 超过限制 {max_sector_pct:.0%}")

    return len(violations) == 0, concentrations, violations


def check_total_exposure(
    total_market_value: float,
    equity: float,
    max_exposure_pct: float = 1.0,
) -> tuple[bool, str]:
    """检查总仓位是否超限."""
    pct = total_market_value / equity if equity > 0 else 0
    if pct > max_exposure_pct:
        return False, f"总仓位 {pct:.1%} 超过限制 {max_exposure_pct:.0%}"
    return True, ''


def dynamic_exposure_adjust(
    base_exposure: float,
    recent_drawdown: float,
    market_trend: str = 'neutral',
) -> float:
    """根据回撤和市场趋势动态调整总仓位.

    回撤越大 -> 仓位越低
    熊市 -> 降低仓位
    """
    factor = 1.0

    # 回撤降仓
    if recent_drawdown > 0.15:
        factor *= 0.5   # 回撤 > 15%, 半仓
    elif recent_drawdown > 0.10:
        factor *= 0.7   # 回撤 > 10%, 七成仓
    elif recent_drawdown > 0.05:
        factor *= 0.85  # 回撤 > 5%, 八五成仓

    # 市场趋势调整
    if market_trend == 'bear':
        factor *= 0.6
    elif market_trend == 'neutral':
        factor *= 0.8

    return round(base_exposure * factor, 4)


def full_risk_check(
    positions: list[dict],
    total_equity: float,
    recent_drawdown: float = 0.0,
    max_single_pct: float = 0.10,
    max_sector_pct: float = 0.30,
    max_positions: int = 10,
) -> PortfolioRiskCheck:
    """完整风控检查."""
    violations = []
    warnings = []

    # 单只仓位检查
    for p in positions:
        ok, msg = check_single_position_limit(
            p.get('value', 0), total_equity, max_single_pct
        )
        if not ok:
            violations.append(f"{p.get('code', '?')}: {msg}")

    # 行业集中度
    _, sectors, sector_violations = check_sector_concentration(positions, max_sector_pct)
    violations.extend(sector_violations)

    # 持仓数量
    if len(positions) > max_positions:
        violations.append(f"持仓数 {len(positions)} 超过限制 {max_positions}")

    # 总仓位
    total_mv = sum(p.get('value', 0) for p in positions)
    ok, msg = check_total_exposure(total_mv, total_equity)
    if not ok:
        violations.append(msg)

    # 回撤警告
    if recent_drawdown > 0.10:
        warnings.append(f"当前回撤 {recent_drawdown:.1%}, 建议降低新开仓频率")
    if recent_drawdown > 0.15:
        warnings.append(f"回撤严重 {recent_drawdown:.1%}, 建议暂停新开仓")

    return PortfolioRiskCheck(
        passed=len(violations) == 0,
        violations=violations,
        warnings=warnings,
        max_allowed_positions=max_positions,
        current_positions=len(positions),
        sector_concentrations=sectors,
        total_exposure_pct=round(total_mv / total_equity, 4) if total_equity > 0 else 0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Portfolio Risk Check')
    parser.add_argument('--portfolio', type=Path, required=True, help='Portfolio JSON')
    args = parser.parse_args()

    if not args.portfolio.exists():
        print(f"Portfolio file not found: {args.portfolio}")
        return 1

    data = json.loads(args.portfolio.read_text(encoding='utf-8'))
    result = full_risk_check(
        positions=data.get('positions', []),
        total_equity=data.get('total_equity', 0),
        recent_drawdown=data.get('recent_drawdown', 0),
    )

    output = {
        'passed': result.passed,
        'violations': result.violations,
        'warnings': result.warnings,
        'current_positions': result.current_positions,
        'total_exposure_pct': result.total_exposure_pct,
        'sector_concentrations': result.sector_concentrations,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
