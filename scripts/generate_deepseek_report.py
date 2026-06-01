#!/usr/bin/env python3
"""Generate P116 daily market observation report using DeepSeek API.

Reads the daily E/F snapshot and diff JSON, formats a prompt respecting the PRD
compliance rules, and calls DeepSeek to output a human-friendly Markdown report.
"""

import argparse
import json
import os
import sys
from pathlib import Path
import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deepseek_context import with_deepseek_context


def load_settings() -> dict:
    settings_path = ROOT / "config" / "settings.yaml"
    if not settings_path.exists():
        return {}
    with settings_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def generate_report(date_str: str, model_name: str) -> Path:
    ymd = date_str.replace("-", "")
    snapshot_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_{ymd}.json"
    diff_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_all_three_ef_diff_{ymd}.json"

    if not snapshot_path.exists() or not diff_path.exists():
        raise FileNotFoundError(
            f"Missing required JSON outputs for {date_str}. Make sure to run export_daily_all_three_ef.py first."
        )

    # 1. Load JSON data
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    diff_data = json.loads(diff_path.read_text(encoding="utf-8"))

    total_count = snapshot_data.get("total", 0)
    entered = diff_data.get("entered", [])
    left = diff_data.get("left", [])
    stayed = diff_data.get("stayed", [])

    # 2. Extract key stocks information for prompt
    entered_summary = [
        f"- {s['stock_name']} ({s['symbol']}): 行业={s['sw_l1']}, 分数和={s['state_score_sum']}, 状态={s['mn1_state']}/{s['w1_state']}/{s['d1_state']}"
        for s in entered[:15]
    ]
    left_summary = [
        f"- {s['stock_name']} ({s['symbol']}): 行业={s['sw_l1']}, 状态={s['mn1_state']}/{s['w1_state']}/{s['d1_state']}"
        for s in left[:15]
    ]
    stayed_summary = [
        f"- {s['stock_name']} ({s['symbol']}): 支撑位={s['d1_sr_support']}, 阻力位={s['d1_sr_resistance']}"
        for s in stayed[:15]
    ]

    # 3. Construct prompt incorporating PRODUCT_PRD rules
    system_prompt = (
        "你是一个专业的量化交易市场状态观察员。你的任务是根据提供的数据，为普通投资者和私域用户撰写一份“每日观察报告”。\n"
        "【合规性天条 - 必须严格遵守】\n"
        "1. 严禁出现以下敏感操作词汇：'买入'、'卖出'、'建仓'、'加仓'、'减仓'、'止盈'、'止损'、'荐股'、'收益承诺'、'赚钱'。\n"
        "2. 必须使用以下合规表述替代：\n"
        "   - 用“观察池/观察名单”替代“推荐买入名单”\n"
        "   - 用“值得复核/重点关注”替代“买入信号”\n"
        "   - 用“状态仍在观察中”或“移出观察池”替代“继续持有/卖出信号”\n"
        "   - 用“防守价/关键位”替代“止损价”\n"
        "   - 用“历史路径相似度”替代“未来肯定涨”\n"
        "3. 在报告的显著位置必须注明：'【Research-Only】本结果仅为技术状态观察，不构成任何投资建议。'\n"
    )

    user_prompt = f"""请根据以下量化观察池的数据，撰写一份日期为 {date_str} 的市场状态观察报告。

【当日概览】
- 满足三周期全 E/F (多周期强趋势共振突破) 的总股数：{total_count} 只
- 今日新进入共振突破状态的品种数量：{len(entered)} 只
- 今日移出共振突破状态的品种数量：{len(left)} 只
- 保持在共振突破状态的品种数量：{len(stayed)} 只

【新进入观察的个股详情 (最多展示15只)】
{chr(10).join(entered_summary) if entered_summary else "无新进入个股"}

【移出观察的个股详情 (最多展示15只)】
{chr(10).join(left_summary) if left_summary else "无移出个股"}

【持续观察中个股的防守位置参考 (最多展示15只)】
{chr(10).join(stayed_summary) if stayed_summary else "无持续观察个股"}

报告格式要求：
1. 【免责声明】放在最顶部。
2. 【大盘与行业洞察】：分析新进入个股主要集中在哪些申万一级行业，这代表资金在往哪些板块聚焦？
3. 【异动状态解读】：挑出2-3只具有代表性的新入池个股，解读其 MN1/W1/D1 的状态共振情况。
4. 【防守关键位提醒】：列出部分重点个股的防守支撑价位，说明若收盘跌破防守位，该状态值得复核或移出观察池。
"""

    # 4. API Call using requests (supports DeepSeek / OpenAI compatible endpoint)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    if not api_key:
        print(
            "Warning: DEEPSEEK_API_KEY environment variable not set. Writing empty report template.",
            file=sys.stderr,
        )
        report_text = f"# 观察报告未生成\n\n请设置 `DEEPSEEK_API_KEY` 环境变量来自动生成由 {model_name} 驱动的智能市场分析。\n"
    else:
        print(f"Calling DeepSeek API ({model_name}) via {api_base}...", flush=True)
        try:
            response = requests.post(
                f"{api_base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_name if model_name != "deepseekV4" else "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": with_deepseek_context(system_prompt)},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
                timeout=60,
            )
            response.raise_for_status()
            res_json = response.json()
            report_text = res_json["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Error calling DeepSeek API: {e}", file=sys.stderr)
            report_text = f"# 观察报告生成失败\n\nAPI 调用出错：{e}\n"

    # 5. Save report to outputs
    report_output_path = ROOT / "outputs" / "p116_daily_all_three_ef" / f"p116_report_{ymd}.md"
    report_output_path.write_text(report_text, encoding="utf-8")

    # Also copy to public directory for serving
    public_report_path = ROOT / "public" / f"p116_report_{ymd}.md"
    public_report_path.write_text(report_text, encoding="utf-8")

    # Copy to latest
    latest_report_path = ROOT / "public" / "p116_report_latest.md"
    latest_report_path.write_text(report_text, encoding="utf-8")

    return report_output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate P116 DeepSeek Observation Report")
    parser.add_argument("--date", required=True, help="Trading date, e.g. 2026-05-20")
    parser.add_argument("--model", help="Override LLM model name")
    args = parser.parse_args()

    settings = load_settings()
    model = args.model or settings.get("llm", {}).get("default_model", "deepseekV4")

    try:
        report_path = generate_report(args.date, model)
        print(f"Successfully generated DeepSeek report:")
        print(f"  Markdown: {report_path}")
        print(f"  Public Latest: {ROOT / 'public' / 'p116_report_latest.md'}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
