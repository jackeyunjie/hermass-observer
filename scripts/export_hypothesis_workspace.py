#!/usr/bin/env python3
"""
export_hypothesis_workspace.py
把 outputs 中已有的假设验证结果，沉淀成 Markdown 到作战室目录。

用法：
  .venv/bin/python scripts/export_hypothesis_workspace.py \
    --hypothesis D1_CONTRACTION_BREAKOUT_OBSERVATION \
    --from 2026-05-01 --to 2026-06-05 \
    [--hypothesis-id H001]
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "data/research/conversations"
OUTS = ROOT / "outputs"

DIRS = {
    "exp": WORKSPACE / "03-假设验证实验",
    "debate": WORKSPACE / "05-多Agent辩论记录",
    "ledger": WORKSPACE / "06-Router权重与决策账本",
    "risk": WORKSPACE / "08-RiskAgent否决案例",
    "case": WORKSPACE / "09-命中与误判案例库",
}


def ensure_dirs():
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)


def find_debate_json(hypothesis: str, d: date) -> Path:
    candidates = [
        OUTS / f"debate/{hypothesis}_{d.strftime('%Y%m%d')}_debate.json",
        OUTS / f"debate/debate_{d.strftime('%Y%m%d')}.json",
        OUTS / f"hypothesis_reviews/{hypothesis}_{d.strftime('%Y%m%d')}_debate.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_router_json(hypothesis: str, d: date) -> Path:
    candidates = [
        OUTS / f"router/{hypothesis}_{d.strftime('%Y%m%d')}_router.json",
        OUTS / f"router/router_decisions_{d.strftime('%Y%m%d')}.json",
        OUTS / f"debate/router_{d.strftime('%Y%m%d')}.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def fmt_future(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "待回填"
    return f"{v:.4f}"


def write_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")
    print(f"[WRITE] {path}")


def generate_exp(h_id: str, d: date, rows: list, debate_path, router_path):
    sample_size = len(rows)
    labels = {}
    veto_count = 0
    for r in rows:
        labels[r.get("final_label", "unknown")] = labels.get(r.get("final_label", "unknown"), 0) + 1
        if r.get("risk_veto"):
            veto_count += 1
    content = f"""---
type: hypothesis_experiment
experiment_id: EXP-{h_id}-{d.strftime('%Y%m%d')}
hypothesis_id: {h_id}
date: {d.isoformat()}
source: decision_observation.duckdb
created_at: {datetime.now().isoformat()}
---

# EXP-{h_id}-{d.strftime('%Y%m%d')}

## 假设关联
- {h_id}

## 实验日期范围
- {d.isoformat()} ~ {d.isoformat()}

## 样本量
- {sample_size}

## 候选选择规则
- 见 hypothesis_candidate_selector.py --date {d.isoformat()}

## 参与 Agent 集合
- W1TrendAgent, D1StructureAgent, VolatilityAgent, MomentumAgent, BoundaryAgent, RiskAgent

## Router 规则版本
- dynamic_weight_router.py (rule-based)

## Ledger 路径
- outputs/decision_observation/decision_observation.duckdb

## 报告路径
- outputs/hypothesis_reviews/{rows[0].get('hypothesis_id', 'UNKNOWN')}_*_review.md

## 结果摘要
- 总样本: {sample_size}
- 标签分布: {json.dumps(labels, ensure_ascii=False)}
- RiskAgent 否决数: {veto_count}

## 指标表
| 指标 | 数值 | 备注 |
|------|------|------|
| 样本量 | {sample_size} | |
| future_r5 回填率 | 待统计 | 当前未回填 |
| future_r20 回填率 | 待统计 | 当前未回填 |
| Precision@10 | 待回填后计算 | |

## 决策结论
- iterate（等待 future outcome 回填）

## 下一步迭代
- 等待 5/20 日后回填收益数据。

## 源文件
- Debate JSON: {debate_path or '未找到'}
- Router JSON: {router_path or '未找到'}
"""
    write_file(DIRS["exp"] / f"EXP-{h_id}-{d.strftime('%Y%m%d')}.md", content)


def generate_debate(h_id: str, d: date, debate_data: dict):
    if not debate_data:
        return
    candidates = debate_data.get("candidate_count", 0)
    agents = debate_data.get("agent_results", {})
    agent_summaries = []
    for agent_id, info in agents.items():
        agent_summaries.append(f"- **{info.get('agent_name', agent_id)}**: {info.get('status', 'ok')}")

    content = f"""---
type: agent_debate_record
hypothesis_id: {h_id}
date: {d.isoformat()}
source: {debate_data.get('_source_file', 'unknown')}
created_at: {datetime.now().isoformat()}
---

# DEBATE-{h_id}-{d.strftime('%Y%m%d')}

## 股票与日期
- 日期: {d.isoformat()}
- 候选数: {candidates}

## 各 Agent 汇总
{chr(10).join(agent_summaries)}

## 冲突点
- （待人工补充典型冲突案例）

## 共振点
- （待人工补充典型共振案例）

## 未决问题
- M30 盘中确认是否必要？
- RiskAgent 权重是否过严？

## 源数据摘要
```json
{json.dumps({"status": debate_data.get("status"), "candidate_count": candidates}, ensure_ascii=False, indent=2)}
```
"""
    write_file(DIRS["debate"] / f"DEBATE-{h_id}-{d.strftime('%Y%m%d')}.md", content)


def generate_ledger(h_id: str, d: date, rows: list):
    lines = []
    for r in rows:
        lines.append(
            f"| {r.get('stock_code')} | {r.get('final_label')} | {r.get('final_score')} | "
            f"{r.get('risk_veto')} | {fmt_future(r.get('future_r5'))} | {fmt_future(r.get('future_r20'))} | "
            f"{r.get('outcome_label') or '待回填'} |"
        )
    content = f"""---
type: router_ledger_review
hypothesis_id: {h_id}
date: {d.isoformat()}
source: outputs/decision_observation/decision_observation.duckdb
created_at: {datetime.now().isoformat()}
---

# LEDGER-{h_id}-{d.strftime('%Y%m%d')}

## 观察列表

| stock_code | final_label | final_score | risk_veto | future_r5 | future_r20 | outcome_label |
|------------|-------------|-------------|-----------|-----------|------------|---------------|
{chr(10).join(lines)}

## Review 结论
- （待回填后补充）

## 规则调整建议
- （待周度复盘后补充）
"""
    write_file(DIRS["ledger"] / f"LEDGER-{h_id}-{d.strftime('%Y%m%d')}.md", content)


def generate_risk_cases(h_id: str, d: date, rows: list):
    for r in rows:
        if not r.get("risk_veto"):
            continue
        stock = r["stock_code"]
        content = f"""---
type: risk_veto_case
case_id: RISK-{h_id}-{d.strftime('%Y%m%d')}-{stock}
stock_code: {stock}
state_date: {d.isoformat()}
hypothesis_id: {h_id}
created_at: {datetime.now().isoformat()}
---

# RISK-{h_id}-{d.strftime('%Y%m%d')}-{stock}

## 否决原因
- 见 Router JSON / decision_observation.duckdb 中 risk_veto=true 记录。

## 风险标签
- （待补充）

## Router 最终标签
- {r.get('final_label')}

## 未来收益（回填）
- future_r5: {fmt_future(r.get('future_r5'))}
- future_r20: {fmt_future(r.get('future_r20'))}

## 否决是否正确（回填后）
- 待回填

## 教训
- （待补充）

## 阈值调整建议
- （待周度复盘后补充）
"""
        write_file(DIRS["risk"] / f"RISK-{h_id}-{d.strftime('%Y%m%d')}-{stock}.md", content)


def generate_hit_miss_cases(h_id: str, d: date, rows: list):
    for r in rows:
        stock = r["stock_code"]
        content = f"""---
type: hit_miss_case
case_id: CASE-{h_id}-{d.strftime('%Y%m%d')}-{stock}
stock_code: {stock}
state_date: {d.isoformat()}
hypothesis_id: {h_id}
created_at: {datetime.now().isoformat()}
---

# CASE-{h_id}-{d.strftime('%Y%m%d')}-{stock}

## 最终标签与得分
- final_label: {r.get('final_label')}
- final_score: {r.get('final_score')}

## Agent 共识
- （见 DEBATE-{h_id}-{d.strftime('%Y%m%d')}.md）

## RiskAgent 观点
- risk_veto: {r.get('risk_veto')}

## 未来收益（回填）
- future_r5: {fmt_future(r.get('future_r5'))}
- future_r20: {fmt_future(r.get('future_r20'))}

## 命中或误判
- 待回填

## 原因分析
- 待回填后补充

## 可复用模式
- 待回填后补充

## 应避免模式
- 待回填后补充
"""
        write_file(DIRS["case"] / f"CASE-{h_id}-{d.strftime('%Y%m%d')}-{stock}.md", content)


def main():
    parser = argparse.ArgumentParser(description="Export hypothesis workspace to Markdown")
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--hypothesis-id", default="H001")
    parser.add_argument("--db", default=str(OUTS / "decision_observation/decision_observation.duckdb"))
    args = parser.parse_args()

    ensure_dirs()
    h_id = args.hypothesis_id

    # 读取 DuckDB
    if not Path(args.db).exists():
        print(f"[WARN] DB not found: {args.db}")
        sys.exit(0)

    con = duckdb.connect(args.db)
    rows = con.execute(f"""
        SELECT * FROM decision_observation
        WHERE hypothesis_id = '{args.hypothesis}'
          AND state_date BETWEEN '{args.from_date}' AND '{args.to_date}'
        ORDER BY state_date, stock_code
    """).fetchdf().to_dict("records")
    con.close()

    if not rows:
        print(f"[WARN] No records for {args.hypothesis} between {args.from_date} and {args.to_date}")

    # 按日期分组
    by_date = {}
    for r in rows:
        d = r["state_date"]
        if isinstance(d, datetime):
            d = d.date()
        by_date.setdefault(d, []).append(r)

    for d, day_rows in sorted(by_date.items()):
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        print(f"[PROCESS] {d_str} ({len(day_rows)} rows)")

        debate_path = find_debate_json(args.hypothesis, d)
        router_path = find_router_json(args.hypothesis, d)

        debate_data = None
        if debate_path:
            try:
                with open(debate_path, "r", encoding="utf-8") as f:
                    debate_data = json.load(f)
                debate_data["_source_file"] = str(debate_path)
            except Exception as e:
                print(f"[WARN] Failed to load debate JSON {debate_path}: {e}")
        else:
            print(f"[WARN] Debate JSON not found for {d_str}")

        if router_path:
            print(f"[INFO] Router JSON found: {router_path}")
        else:
            print(f"[WARN] Router JSON not found for {d_str}")

        generate_exp(h_id, d, day_rows, debate_path, router_path)
        generate_debate(h_id, d, debate_data or {})
        generate_ledger(h_id, d, day_rows)
        generate_risk_cases(h_id, d, day_rows)
        generate_hit_miss_cases(h_id, d, day_rows)

    print("[OK] Export complete.")


if __name__ == "__main__":
    main()
