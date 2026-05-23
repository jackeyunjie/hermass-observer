#!/usr/bin/env python3
"""AI Research Loop — 每周基本面与技术面共振洞察。

结合 L1/L2 数据库（fundamental_evidence 和 p116_foundation），
通过 SQL 筛选出特定特征的股票池，然后交给 DeepSeek (L3) 解释和发现。

解答 5 个核心问题：
1. 哪些公司基本面身份被重新理解 (基于产业链/主营构成的变化，暂用静态分析替代)
2. 哪些概念是真主业，哪些只是蹭概念 (概念包含热门词，但 core_business_purity 高低差异)
3. 哪些公司出现产业链地位改善迹象 (ROE/毛利率高分位，排名提升)
4. 哪些技术强股基本面不配合 (P116 强势，但 quality_score 极低)
5. 哪些基本面强股技术面刚开始改善 (quality_score 极高，且 P116 刚进入 VCP/E/F 状态)

用法：
  python3 scripts/fundamental_ai_research_loop.py --date 2026-05-21
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deepseek_context import with_deepseek_context

EVIDENCE_DB = ROOT / "outputs" / "fundamental" / "fundamental_evidence.duckdb"
P116_DB_DIR = ROOT / "outputs"

SYSTEM_PROMPT = """你是一个顶级的 A 股量化基本面与产业研究员（Research-Only）。

你的任务是基于我提供的「数据库客观筛选结果」，进行深度的产业逻辑与叙事解释。
不要给出任何买卖建议。你的目标是：
1. 解释这些数据背后的产业叙事或基本面原因
2. 发现潜在的预期差（例如：为什么某个技术强股基本面很差？是因为处于行业反转初期，还是纯资金炒作？）
3. 识别出哪些是真主业（有营收/利润支撑），哪些是纯蹭概念

你的输出必须是清晰的、一针见血的大段落分析，不爹味，保持极度专业。
指标定义必须严格遵守：
- 主业纯度/core_business_purity = 经营活动净收益/利润总额；缺失时用营业利润/利润总额近似。它不是营收/净利润。
- 现金含金量/cash_quality = 经营活动现金流量净额/净利润。
- 盈利质量/earnings_quality = 扣非归母净利润/归母净利润。
- 质量分是 Python 根据上述 L2 因子计算的 0-100 分，极端分母导致的异常比例已经在输入中标记为“异常值”。
不要改写这些公式。如果数据不足或比例异常，只能说“需要回看分母/一次性因素”，不能编造财务事实。
请对提供的 5 个问题逐一进行深度点评。
直接输出 Markdown 格式的报告。"""


def call_deepseek(user_prompt: str) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_base = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")
    if not api_key:
        return "⚠️ DEEPSEEK_API_KEY 未设置，跳过 AI 分析。以下为原始数据特征："
    
    url = f"{api_base}/v1/chat/completions"
    body = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": with_deepseek_context(SYSTEM_PROMPT)},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4000
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠️ 调用 DeepSeek 失败: {e}"


def fmt_pct(value, anomaly_threshold: float = 3.0) -> str:
    if value is None:
        return "N/A"
    ratio = float(value)
    if abs(ratio) > anomaly_threshold:
        return f"异常值 {ratio:.2f}x"
    return f"{ratio:.2%}"


def fmt_num(value) -> str:
    return "N/A" if value is None else f"{float(value):.1f}"


def clip_text(value, max_len: int = 80) -> str:
    if value is None:
        return "N/A"
    text = str(value).replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def run_research_loop(date_str: str) -> None:
    p116_path = P116_DB_DIR / f"p116_foundation_{date_str.replace('-','')}" / "p116_foundation.duckdb"
    
    con = duckdb.connect()
    con.execute(f"ATTACH '{EVIDENCE_DB}' AS fund")
    
    has_p116 = p116_path.exists()
    if has_p116:
        con.execute(f"ATTACH '{p116_path}' AS p116")
        
    prompt_lines = [f"## 数据截面日期: {date_str}", ""]

    # 1. 基本面身份重新理解
    q1 = """
    SELECT p.stock_code, p.stock_name, p.sw_l1, p.sw_l2, p.sw_l3, p.main_business,
           q.quality_score, q.core_business_purity
    FROM fund.ifind_industry_chain_profile p
    LEFT JOIN fund.fundamental_quality_score q
      ON p.stock_code = q.stock_code AND q.as_of_date = ?
    JOIN fund.ifind_tracking_pool t
      ON p.stock_code = t.stock_code AND t.active = true
    WHERE p.as_of_date = ?
    ORDER BY COALESCE(q.quality_score, -1) DESC, p.stock_code
    LIMIT 20
    """
    rows1 = con.execute(q1, (date_str, date_str)).fetchall()
    prompt_lines.append("### 议题1：股票池公司的【基本面身份重新理解】基础数据")
    prompt_lines.append("（注：这里不是让模型猜公司，而是用 iFinD 产业链/主营/质量分重新定义公司身份）")
    for r in rows1:
        prompt_lines.append(
            f"- {r[1]} ({r[0]}): 行业={r[2]}/{r[3]}/{r[4]} | "
            f"质量分={fmt_num(r[6])} | 主业纯度={fmt_pct(r[7])} | 主营={clip_text(r[5], 70)}"
        )
    prompt_lines.append("")
    
    # 2. 真主业 vs 蹭概念
    # 筛选：有热门概念，分别抽主业纯度高/低两端，避免只把分母异常的高倍数喂给 LLM。
    q2 = """
    SELECT p.stock_code, p.stock_name, p.ths_concepts, q.core_business_purity, q.quality_score
    FROM fund.ifind_industry_chain_profile p
    JOIN fund.fundamental_quality_score q ON p.stock_code = q.stock_code
    WHERE p.as_of_date = ? AND q.as_of_date = ?
      AND p.ths_concepts IS NOT NULL
      AND (p.ths_concepts LIKE '%算力%' OR p.ths_concepts LIKE '%低空经济%' OR p.ths_concepts LIKE '%机器人%')
    """
    rows2_all = con.execute(q2, (date_str, date_str)).fetchall()
    rows2_valid = [r for r in rows2_all if r[3] is not None]
    rows2_high = sorted(rows2_valid, key=lambda r: r[3], reverse=True)[:8]
    rows2_low = sorted(rows2_valid, key=lambda r: r[3])[:8]
    prompt_lines.append("### 议题2：热门概念中的【真主业 vs 蹭概念】对比数据")
    prompt_lines.append("（注：主业纯度 > 80% 倾向真主业，< 30% 倾向边缘蹭概念；超过 3x 标为异常值，通常需要回看利润分母）")
    prompt_lines.append("#### 主业纯度高的一端")
    for r in rows2_high:
        prompt_lines.append(
            f"- {r[1]} ({r[0]}): 纯度={fmt_pct(r[3])} | "
            f"质量分={fmt_num(r[4])} | 概念={clip_text(r[2], 60)}"
        )
    prompt_lines.append("#### 主业纯度低的一端")
    for r in rows2_low:
        prompt_lines.append(
            f"- {r[1]} ({r[0]}): 纯度={fmt_pct(r[3])} | "
            f"质量分={fmt_num(r[4])} | 概念={clip_text(r[2], 60)}"
        )
    prompt_lines.append("")

    # 3. 产业链地位改善迹象
    # 当前首版没有历史环比，因此先用高质量分 + 高主业纯度/现金质量做“改善候选基线”。
    q3 = """
    SELECT p.stock_code, p.stock_name, p.sw_l1, p.sw_l2, p.sw_l3,
           q.quality_score, q.core_business_purity, q.cash_quality, q.earnings_quality,
           p.main_product_names
    FROM fund.ifind_industry_chain_profile p
    JOIN fund.fundamental_quality_score q ON p.stock_code = q.stock_code
    WHERE p.as_of_date = ? AND q.as_of_date = ?
      AND q.quality_score >= 90
      AND q.core_business_purity BETWEEN 0.7 AND 3.0
      AND q.cash_quality BETWEEN 0.5 AND 3.0
      AND q.earnings_quality BETWEEN 0.5 AND 3.0
    ORDER BY q.quality_score DESC, q.core_business_purity DESC NULLS LAST
    LIMIT 20
    """
    rows3 = con.execute(q3, (date_str, date_str)).fetchall()
    prompt_lines.append("### 议题3：【产业链地位改善迹象】候选基线")
    prompt_lines.append("（注：首版暂无历史环比，先用高质量分 + 合理区间内的主业纯度/现金质量/盈利质量作为后续跟踪基线）")
    for r in rows3:
        prompt_lines.append(
            f"- {r[1]} ({r[0]}): 行业={r[2]}/{r[3]}/{r[4]} | "
            f"质量分={fmt_num(r[5])} | 主业纯度={fmt_pct(r[6])} | "
            f"现金含金量={fmt_pct(r[7])} | 盈利质量={fmt_pct(r[8])} | 产品={clip_text(r[9], 60)}"
        )
    prompt_lines.append("")

    # 4. 技术强股基本面不配合
    if has_p116:
        q4 = """
        SELECT s.stock_code, q.stock_name, s.d1_state_hex as d1_state, q.quality_score, q.core_business_purity
        FROM p116.d1_perspective_state s
        JOIN fund.fundamental_quality_score q ON s.stock_code = q.stock_code
        WHERE s.state_date = ? AND q.as_of_date = ?
          AND s.d1_state_hex IN ('E', 'F')
          AND q.quality_score < 30
        ORDER BY q.quality_score ASC
        LIMIT 10
        """
        rows4 = con.execute(q4, (date_str, date_str)).fetchall()
        prompt_lines.append("### 议题4：【技术面极强 (D1=E/F) 但基本面极差 (质量分<30)】的异常品种")
        for r in rows4:
            prompt_lines.append(f"- {r[1]} ({r[0]}): D1={r[2]} | 质量分={fmt_num(r[3])} | 主业纯度={fmt_pct(r[4])}")
        prompt_lines.append("")
    else:
        prompt_lines.append("### 议题4：【技术面极强但基本面极差】的异常品种")
        prompt_lines.append(f"- 未找到 P116 foundation DB: {p116_path}")
        prompt_lines.append("")
    
    # 5. 基本面强股技术面刚改善
    if has_p116:
        q5 = """
        SELECT s.stock_code, q.stock_name, s.d1_state_hex as d1_state, q.quality_score, q.earnings_quality
        FROM p116.d1_perspective_state s
        JOIN fund.fundamental_quality_score q ON s.stock_code = q.stock_code
        WHERE s.state_date = ? AND q.as_of_date = ?
          AND s.d1_state_hex IN ('B', 'C', 'E')
          AND q.quality_score > 80
        ORDER BY q.quality_score DESC
        LIMIT 10
        """
        rows5 = con.execute(q5, (date_str, date_str)).fetchall()
        prompt_lines.append("### 议题5：【基本面极优 (质量分>80) 且技术面刚启动或维持强势】的共振品种")
        for r in rows5:
            prompt_lines.append(f"- {r[1]} ({r[0]}): D1={r[2]} | 质量分={fmt_num(r[3])} | 盈利质量={fmt_pct(r[4])}")
        prompt_lines.append("")
    else:
        prompt_lines.append("### 议题5：【基本面极优且技术面刚启动或维持强势】的共振品种")
        prompt_lines.append(f"- 未找到 P116 foundation DB: {p116_path}")
        prompt_lines.append("")
        
    con.close()
    
    prompt = "\n".join(prompt_lines)
    print("======== SQL 筛选数据 ========")
    print(prompt)
    print("=============================\n")
    
    print("正在调用 DeepSeek 进行 AI Research Loop 分析...")
    report = call_deepseek(prompt)
    
    output_dir = ROOT / "outputs" / "fundamental"
    report_path = output_dir / f"ai_research_loop_{date_str.replace('-','')}.md"
    prompt_path = output_dir / f"ai_research_loop_input_{date_str.replace('-','')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    report_path.write_text(prompt + "\n\n" + report, encoding="utf-8")
    print(f"\n✅ 报告已生成并保存至: {report_path}")
    print(f"✅ SQL 输入已保存至: {prompt_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Research Loop Weekly Generator")
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    run_research_loop(args.date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
