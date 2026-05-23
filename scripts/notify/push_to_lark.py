"""Push daily recommendation to Lark (飞书).

通过 lark-cli 发送每日推荐消息到指定飞书群。

Usage:
    python3 -m scripts.notify.push_to_lark --date 2026-05-20
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def format_message(portfolio: dict) -> str:
    """格式化推荐消息 (飞书 Markdown)."""
    date = portfolio.get('date', '')
    positions = portfolio.get('positions', [])
    dd = portfolio.get('drawdown_state', {})

    lines = [
        f"**Hermass Observer 每日推荐** - {date}",
        "",
        f"组合规模: {portfolio.get('positions_count', 0)} 只 | "
        f"投入: {portfolio.get('total_invested', 0):,.0f} | "
        f"回撤: {dd.get('current_drawdown', 0):.1%}",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(positions, 1):
        grade = p.get('quality_grade', '')
        lines.append(
            f"**{i}. {p['stock_code']}** {p.get('stock_name', '')}\n"
            f"   EF={p['ef_count']}/3  质量={grade}({p.get('quality_score', 0):.0f})\n"
            f"   入场: {p['entry_price']:.2f}  "
            f"止损: {p['stop_loss']:.2f}(-{p.get('stop_loss_distance', 0):.1%})  "
            f"止盈: {p['take_profit']:.2f}(+{p.get('reward_pct', 0):.1%})\n"
            f"   盈亏比: {p.get('rr_ratio', 0):.1f}  "
            f"仓位: {p.get('position_pct', 0):.1%}"
        )
        lines.append("")

    lines.append("---")
    lines.append("*Research-Only, 不构成投资建议*")
    return "\n".join(lines)


def format_simple_text(portfolio: dict) -> str:
    """纯文本格式 (用于不支持 markdown 的场景)."""
    date = portfolio.get('date', '')
    positions = portfolio.get('positions', [])

    lines = [f"Hermass Observer 推荐 - {date}", ""]
    for i, p in enumerate(positions, 1):
        lines.append(
            f"{i}. {p['stock_code']} EF={p['ef_count']} "
            f"Q={p.get('quality_score', 0):.0f} "
            f"入场{p['entry_price']:.2f} "
            f"止损{p['stop_loss']:.2f} "
            f"止盈{p['take_profit']:.2f}"
        )
    lines.append("")
    lines.append("Research-Only")
    return "\n".join(lines)


def push_via_lark_cli(
    message: str,
    webhook_url: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """通过 lark-cli 发送消息.

    Args:
        message: 消息内容 (Markdown)
        webhook_url: Webhook URL (群机器人)
        chat_id: 飞书群 chat_id

    Returns:
        是否发送成功
    """
    # 尝试使用 lark-cli
    try:
        if webhook_url:
            # Webhook 方式
            result = subprocess.run(
                ['lark-cli', 'im', '+send', '--webhook', webhook_url, '--text', message],
                capture_output=True, text=True, timeout=30,
            )
        elif chat_id:
            # Chat ID 方式
            result = subprocess.run(
                ['lark-cli', 'im', '+send', '--chat-id', chat_id, '--text', message],
                capture_output=True, text=True, timeout=30,
            )
        else:
            print("No webhook_url or chat_id configured, skipping Lark push")
            return False

        if result.returncode == 0:
            print(f"Lark push success")
            return True
        else:
            print(f"Lark push failed: {result.stderr}")
            return False

    except FileNotFoundError:
        print("lark-cli not found, skipping Lark push")
        return False
    except Exception as e:
        print(f"Lark push error: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description='Push daily recommendation to Lark')
    parser.add_argument('--date', required=True)
    parser.add_argument('--portfolio-json', type=Path, help='Portfolio JSON file')
    parser.add_argument('--webhook-url', help='Lark webhook URL')
    parser.add_argument('--chat-id', help='Lark chat_id')
    parser.add_argument('--dry-run', action='store_true', help='Only print, do not send')
    args = parser.parse_args()

    # 加载 portfolio
    portfolio_path = args.portfolio_json
    if portfolio_path is None:
        ymd = args.date.replace('-', '')
        portfolio_path = ROOT / 'outputs' / f'recommend_{ymd}' / 'portfolio.json'

    if not portfolio_path.exists():
        print(f"Portfolio not found: {portfolio_path}")
        print("Run: make recommend first")
        return 1

    portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
    message = format_message(portfolio)

    if args.dry_run:
        print("=== Dry Run ===")
        print(message)
        return 0

    # 推送
    success = push_via_lark_cli(
        message,
        webhook_url=args.webhook_url,
        chat_id=args.chat_id,
    )
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
