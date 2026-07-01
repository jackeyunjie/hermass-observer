#!/usr/bin/env python3
"""观象 30 问覆盖包执行脚本（Kimi 任务）。

运行：
    .venv/bin/python scripts/run_guanxiang_30q_coverage.py

说明：
    脚本内置 mock workflow HTTP 响应，不依赖 19999 端口或外部服务。
    若要打真实 webhook，设置 GUANXIANG_30Q_USE_REAL_WORKFLOW=1。
"""
from __future__ import annotations

import base64
import csv
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

# 必须在导入 web.main 前设置环境变量
os.environ.setdefault("HERMASS_AI_WORKFLOW_PROVIDER", "generic")
os.environ.setdefault("HERMASS_AI_WORKFLOW_URL", "http://127.0.0.1:19999/webhook")
os.environ.setdefault("HERMASS_AI_WORKFLOW_API_KEY", "test-key")
os.environ.setdefault("HERMASS_AI_WORKFLOW_TIMEOUT_SEC", "10")
USE_REAL_WORKFLOW = os.environ.get("GUANXIANG_30Q_USE_REAL_WORKFLOW", "").strip().lower() in {
    "1",
    "true",
    "yes",
}

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.main import app

client = TestClient(app)


def _basic_auth_header(username: str = "hermass-test", password: str = "Hermass2026!Lab") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


AUTH_HEADERS = _basic_auth_header()

QUESTIONS = [
    ("A", "泛问题", "你能帮我做什么"),
    ("A", "泛问题", "你是谁"),
    ("A", "泛问题", "怎么使用这个系统"),
    ("B", "市场问题", "现在能不能做"),
    ("B", "市场问题", "市场怎么样"),
    ("B", "市场问题", "今天能买吗"),
    ("B", "市场问题", "要不要等待"),
    ("C", "行业问题", "今天先看什么方向"),
    ("C", "行业问题", "哪个行业好"),
    ("C", "行业问题", "顺风方向是什么"),
    ("C", "行业问题", "板块轮动怎么看"),
    ("D", "个股问题", "000021怎么看"),
    ("D", "个股问题", "600519怎么样"),
    ("D", "个股问题", "帮我看一只票"),
    ("D", "个股问题", "这只票如何"),
    ("D", "个股问题", "它现在什么状态"),
    ("E", "基本面/价值", "用价值分析看000021"),
    ("E", "基本面/价值", "基本面如何"),
    ("E", "基本面/价值", "八大块分析"),
    ("E", "基本面/价值", "深度价值"),
    ("F", "教学问题", "什么是State E/F"),
    ("F", "教学问题", "VCP是什么"),
    ("F", "教学问题", "2560什么意思"),
    ("F", "教学问题", "多周期怎么看"),
    ("G", "导航问题", "我应该先去哪页"),
    ("G", "导航问题", "怎么看自选"),
    ("G", "导航问题", "设置在哪"),
    ("H", "新概念", "解释一下低空经济这个概念"),
    ("H", "新概念", "固态电池产业链"),
    ("H", "新概念", "量子计算概念股"),
]


ANSWERS = {
    "你能帮我做什么": "我是观象外部助手，可以解释概念、整理资料、给出页面导航，但不会提供自动交易或仓位建议。",
    "你是谁": "我是观象的外部工作流扩展回答，用于补充开放问题解释；当前回答暂无 Hermass 本地数据证据支持。",
    "怎么使用这个系统": "建议按市场、行业、研究、执行的顺序浏览；若需要具体标的，请回到 Hermass 本地研究页验证数据。",
    "现在能不能做": "外部工作流无法判断今日真实市场状态，请以 Hermass 本地市场页和 State Cube 证据为准。",
    "市场怎么样": "这里可以解释市场观察框架，但当前 mock workflow 不包含实时市场数据。",
    "今天能买吗": "我不能给出买卖或仓位建议；当前仅能说明应先查本地市场阶段、行业承接和个股位置。",
    "要不要等待": "等待与否需要本地多周期状态和风险边界支持；本回答只提供解释框架。",
    "今天先看什么方向": "可先从政策、产业链和行业轮动框架缩圈，但具体方向必须回到本地行业轮动数据确认。",
    "哪个行业好": "行业好坏需要行业轮动、资金承接和成分股共振验证；当前回答暂无本地行业数据支持。",
    "顺风方向是什么": "顺风方向通常来自市场环境、行业承接和个股结构共振；当前只说明方法，不替代本地数据。",
    "板块轮动怎么看": "板块轮动可看扩散、持续性、资金确认和龙头带动；当前无实时板块轮动证据。",
    "000021怎么看": "外部工作流只能提示应回到 000021 的 MN1/W1/D1、资金流和研究页证据，不输出具体结论。",
    "600519怎么样": "外部工作流只能提示检查 600519 的多周期结构、估值和行业位置，不能替代本地研究数据。",
    "帮我看一只票": "请先给出 6 位股票代码；外部工作流可解释框架，本地研究页负责实际证据。",
    "这只票如何": "若没有上下文股票代码，我无法确认对象；请回到本地会话记忆或补充代码。",
    "它现在什么状态": "代词问题需要本地会话记忆和 State 数据支持；当前外部工作流只提示核验路径。",
    "用价值分析看000021": "价值分析需要主营、财务、估值、股东和市场观点证据；当前只给出分析框架。",
    "基本面如何": "基本面要看营收、利润、现金流、ROE、负债和行业位置；当前无本地财务数据支持。",
    "八大块分析": "八大块可按公司、行业、财务、估值、股东、市场观点、风险、周期位置展开。",
    "深度价值": "深度价值应结合财务质量、估值分位和周期位置；当前回答不包含真实本地数据。",
    "什么是stateef": "State E/F 是 Hermass 多周期状态编码中的状态标识，需结合具体周期和价格位置解释。",
    "vcp是什么": "VCP 是波动收缩形态，重点看收缩、成交量、关键位和突破后的确认。",
    "2560什么意思": "2560 是项目中的策略观察口径之一，通常围绕周期结构、位置和确认条件使用。",
    "多周期怎么看": "多周期先看大周期环境，再看周线承接，最后看日线位置，避免只看一个周期。",
    "我应该先去哪页": "建议先看市场页，再看行业页，最后进入研究页或执行页。",
    "怎么看自选": "自选应看结构、策略适配、风险边界和最新观察记录，不只看涨跌。",
    "设置在哪": "设置入口通常在页面导航或管理区，具体以当前 Hermass 前端入口为准。",
    "解释一下低空经济这个概念": "低空经济指围绕低空空域、通用航空、无人机和相关服务形成的产业活动。",
    "固态电池产业链": "固态电池产业链通常包括材料、电解质、电芯、设备和下游应用环节。",
    "量子计算概念股": "量子计算概念涉及硬件、算法、通信和安全等方向；具体标的需用本地数据核验。",
}


class FakeWorkflowResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _normalize_question(message: str) -> str:
    return str(message).strip().lower().replace(" ", "").replace("/", "")


def fake_workflow_post(url, headers, json, timeout):
    guardrails = json.get("guardrails") or {}
    required = (
        "research_only",
        "no_trade_execution",
        "no_position_sizing",
        "must_disclose_if_no_local_evidence",
    )
    if not all(guardrails.get(key) is True for key in required):
        raise RuntimeError("missing workflow guardrails")

    message = str(json.get("message") or "")
    answer = ANSWERS.get(
        _normalize_question(message),
        "外部工作流已收到问题，但当前没有 Hermass 本地数据证据，建议回到本地页面核验。",
    )
    return FakeWorkflowResponse(
        {
            "answer": answer,
            "why": "命中脚本内置 mock 外部工作流知识库。",
            "multi_cycle_view": "",
            "single_cycle_position": "",
            "avoid": "不要把外部工作流回答直接当成本地数据结论，不要据此下单或调整仓位。",
            "next_actions": [{"label": "打开首页", "url": "/"}],
            "sources": ["mock_workflow_knowledge"],
            "freshness_note": "Mock 外部工作流生成，暂无本地实时数据支持。",
        }
    )


def query(message: str, use_llm: bool, force_workflow: bool = False) -> dict:
    kwargs = {
        "message": message,
        "page_context": "/",
        "mode": "chat",
        "use_llm": use_llm,
    }
    if force_workflow:
        if USE_REAL_WORKFLOW:
            with patch("agently_adapter.qa_entry.handle", return_value=None):
                r = client.post("/api/chat/query", headers=AUTH_HEADERS, json=kwargs)
        else:
            with patch("agently_adapter.qa_entry.handle", return_value=None), \
                 patch("agently_adapter.workflow_bridge.requests.post", side_effect=fake_workflow_post):
                r = client.post("/api/chat/query", headers=AUTH_HEADERS, json=kwargs)
    else:
        r = client.post("/api/chat/query", headers=AUTH_HEADERS, json=kwargs)
    return r.json() if r.status_code == 200 else {"_error": True, "status_code": r.status_code, "answer": ""}


def run():
    rows = []
    issues = []
    today = date.today().isoformat()
    out_dir = Path("outputs/reviews")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"开始 30 问覆盖测试（{today}）\n")

    for idx, (cat, label, msg) in enumerate(QUESTIONS, 1):
        # 路径 1：规则回答（use_llm=false）
        rule_resp = query(msg, use_llm=False)
        # 路径 2：LLM+workflow（use_llm=true, Agently 强制失败以走 workflow）
        wf_resp = query(msg, use_llm=True, force_workflow=True)

        for path_name, resp in (("规则", rule_resp), ("LLM+WF", wf_resp)):
            provider = resp.get("provider", "")
            data_support = resp.get("data_support", "")
            support_note = resp.get("support_note", "")
            sources = ",".join(resp.get("sources", []))
            answer = resp.get("answer", "")[:120].replace("\n", " ")
            error = "是" if resp.get("_error") else "否"
            has_local = "是" if data_support in ("local_data", "rule_only") else "否"
            rows.append({
                "id": idx,
                "category": cat,
                "type": label,
                "question": msg,
                "path": path_name,
                "provider": provider,
                "data_support": data_support,
                "support_note": support_note[:80],
                "sources": sources,
                "answer_preview": answer,
                "has_local_evidence": has_local,
                "error": error,
            })

            if not resp.get("answer"):
                issues.append(f"{idx:02d} {path_name} answer 为空: {msg}")
            if path_name == "规则":
                # 规则路径允许 rule_based 或 deepseek_direct，不应落到外部 workflow
                if provider.startswith("workflow_"):
                    issues.append(f"{idx:02d} 规则路径不应命中 workflow: {provider}")
            if path_name == "LLM+WF":
                # 外部工作流回答必须带披露、不带伪造本地源
                if provider.startswith("workflow_"):
                    if data_support != "llm_only":
                        issues.append(f"{idx:02d} LLM+WF workflow 路径 data_support 非 llm_only: {data_support}")
                    if "暂无实际数据支持" not in support_note:
                        issues.append(f"{idx:02d} LLM+WF support_note 缺少披露: {support_note}")
                    forbidden_sources = {"daily_snapshot", "research_evidence", "state_cube", "p116_foundation"}
                    leaked = sorted(forbidden_sources & set(resp.get("sources") or []))
                    if leaked:
                        issues.append(f"{idx:02d} LLM+WF sources 伪造本地源: {','.join(leaked)}")

        # 终端进度
        rule_p = rule_resp.get("provider", "")[:15]
        wf_p = wf_resp.get("provider", "")[:15]
        print(f"{idx:02d}. [{label}] {msg[:30]:<30} | 规则={rule_p:<15} | WF={wf_p:<15}")

    # 写 CSV
    csv_path = out_dir / f"guanxiang_30q_coverage_{today}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    # 写 Markdown 报告
    md_path = out_dir / f"guanxiang_30q_coverage_{today}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 观象 30 问覆盖报告（{today}）\n\n")
        f.write("## 统计\n\n")
        wf_rows = [r for r in rows if r["path"] == "LLM+WF"]
        rule_rows = [r for r in rows if r["path"] == "规则"]
        wf_hit = sum(1 for r in wf_rows if r["provider"].startswith("workflow_"))
        rule_local = sum(1 for r in rule_rows if not r["provider"].startswith("workflow_"))
        f.write(f"- 总问题数：{len(QUESTIONS)}\n")
        f.write(f"- 规则路径未落 workflow（本地规则/DeepSeek）：{rule_local}/{len(rule_rows)}\n")
        f.write(f"- LLM+WF 路径命中 workflow：{wf_hit}/{len(wf_rows)}\n")
        f.write(f"- 错误数：{sum(1 for r in rows if r['error'] == '是')}\n\n")
        f.write(f"- 覆盖断言问题数：{len(issues)}\n\n")
        if wf_hit < 15:
            issues.append(f"LLM+WF workflow 覆盖率不足：{wf_hit}/{len(wf_rows)} < 15")

        f.write("## 详细矩阵\n\n")
        f.write("| id | 类型 | 问题 | 路径 | provider | data_support | sources | 本地证据 | 错误 |\n")
        f.write("|----|------|------|------|----------|--------------|---------|----------|------|\n")
        for r in rows:
            f.write(f"| {r['id']} | {r['type']} | {r['question'][:24]} | {r['path']} | {r['provider'][:18]} | {r['data_support']} | {r['sources'][:30]} | {r['has_local_evidence']} | {r['error']} |\n")

        if issues:
            f.write("\n## 覆盖断言问题\n\n")
            for issue in issues:
                f.write(f"- {issue}\n")

        f.write("\n## 下一步建议\n\n")
        f.write("1. 检查 provider 非预期的项，确认路由是否正确。\n")
        f.write("2. 对 `data_support=llm_only` 但回答涉及具体股票/市场的，确认是否应有本地数据。\n")
        f.write("3. 部署到服务器后，用真实 N8N/Dify/Coze 复测 30 问。\n")

    print(f"\n完成。")
    print(f"CSV: {csv_path}")
    print(f"MD:  {md_path}")
    if issues:
        print("\n覆盖断言失败：")
        for issue in issues:
            print(f"- {issue}")
        sys.exit(1)


if __name__ == "__main__":
    run()
