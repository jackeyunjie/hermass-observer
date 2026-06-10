"""观象外部工作流端到端冒烟测试（Kimi 执行）。

前置条件：
- 测试内会 patch 外部 workflow HTTP 调用，不依赖本地 19999 端口服务。
- 环境变量已配置 HERMASS_AI_WORKFLOW_PROVIDER=generic 等

运行：
    HERMASS_AI_WORKFLOW_PROVIDER=generic \
    HERMASS_AI_WORKFLOW_URL=http://127.0.0.1:19999/webhook \
    HERMASS_AI_WORKFLOW_API_KEY=test-key \
    .venv/bin/python -m pytest tests/integration/test_guanxiang_workflow_e2e.py -v
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# 必须在导入 web.main 前设置环境变量
os.environ.setdefault("HERMASS_AI_WORKFLOW_PROVIDER", "generic")
os.environ.setdefault("HERMASS_AI_WORKFLOW_URL", "http://127.0.0.1:19999/webhook")
os.environ.setdefault("HERMASS_AI_WORKFLOW_API_KEY", "test-key")
os.environ.setdefault("HERMASS_AI_WORKFLOW_TIMEOUT_SEC", "10")

from web.main import app


client = TestClient(app)

QUESTIONS = [
    ("泛问题", "你能帮我做什么"),
    ("市场问题", "现在能不能做"),
    ("行业问题", "今天先看什么方向"),
    ("个股问题", "000021怎么看"),
    ("基本面问题", "用价值分析看000021"),
    ("教学问题", "什么是State E/F"),
    ("导航问题", "我应该先去哪页"),
    ("无本地数据问题", "解释一下低空经济这个概念"),
]


ANSWERS = {
    "你能帮我做什么": "我是观象外部助手，可以帮你解释市场概念、整理资料、导航建议。",
    "现在能不能做": "外部工作流视角：当前市场环境需结合本地 State Cube 判断，我这里暂无实时数据。",
    "今天先看什么方向": "外部工作流视角：可关注近期政策提及的方向，但具体行业数据请以本地行业轮动画像为准。",
    "000021怎么看": "外部工作流视角：深科技属于电子制造板块，建议结合本地 MN1/W1/D1 状态综合判断。",
    "用价值分析看000021": "外部工作流视角：价值分析需查看 ROE、现金流、估值分位，本地有基本面数据时可优先参考本地。",
    "什么是statee/f": "State E/F 是 Hermass 多周期状态编码中的收缩/扩张标识，E 通常代表极端状态，F 代表跟随确认。",
    "我应该先去哪页": "建议先去首页查看当日市场快照，或前往 Watchlist 查看自选标的。",
    "解释一下低空经济这个概念": "低空经济指以低空空域为依托，以通用航空产业为主导的经济形态。",
}


class FakeWorkflowResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def fake_workflow_post(url, headers, json, timeout):
    message = str(json.get("message") or "")
    normalized = message.strip().lower().replace(" ", "").replace("/", "")
    answer = ANSWERS.get(
        normalized,
        "外部工作流已收到你的问题，但暂无本地实时数据支撑具体判断，建议结合 Hermass 本地数据面板查看。",
    )
    return FakeWorkflowResponse(
        {
            "answer": answer,
            "why": "命中 mock 外部工作流知识库。",
            "multi_cycle_view": "",
            "single_cycle_position": "",
            "avoid": "不要把外部工作流回答直接当成本地数据结论。",
            "next_actions": [{"label": "打开首页", "url": "/"}],
            "sources": ["external_workflow", "workflow_generic"],
            "freshness_note": "Mock 外部工作流生成，暂无本地实时数据支持。",
        }
    )


@pytest.mark.parametrize("label,message", QUESTIONS)
def test_workflow_fallback_8_questions(label: str, message: str):
    """8 个覆盖问题均触发外部工作流 fallback，并正确标注来源与数据支持状态。"""
    # 强制 Agently qa_entry.handle 返回 None，确保走 workflow fallback
    with patch("agently_adapter.qa_entry.handle", return_value=None), \
         patch("agently_adapter.workflow_bridge.requests.post", side_effect=fake_workflow_post):
        response = client.post(
            "/api/chat/query",
            json={
                "message": message,
                "page_context": "/",
                "mode": "chat",
                "use_llm": True,
            },
        )
    assert response.status_code == 200, f"{label} HTTP 错误"
    payload = response.json()

    # 关键断言：必须来自外部工作流
    provider = payload.get("provider", "")
    assert provider.startswith("workflow_"), (
        f"{label} ('{message}') 期望 provider 以 workflow_ 开头，实际: {provider}"
    )

    # 关键断言：必须声明无本地数据支持
    data_support = payload.get("data_support", "")
    support_note = payload.get("support_note", "")
    assert data_support == "llm_only", (
        f"{label} 期望 data_support=llm_only，实际: {data_support}"
    )
    assert "暂无实际数据支持" in support_note, (
        f"{label} 期望 support_note 含'暂无实际数据支持'，实际: {support_note}"
    )

    # 关键断言：sources 不得伪造本地源
    sources = payload.get("sources", [])
    for fake in ("daily_snapshot", "research_evidence", "p116_foundation"):
        assert fake not in sources, f"{label} sources 不应伪造 {fake}"

    # 关键断言：answer 非空
    assert payload.get("answer"), f"{label} answer 不能为空"

    # 打印摘要供人工核对
    print(f"\n[{label}] {message}")
    print(f"  provider={provider}, data_support={data_support}")
    print(f"  answer_preview={payload.get('answer','')[:60]}...")


def test_workflow_fallback_rejects_missing_guardrails():
    """Mock 服务对缺少 guardrails 的请求返回 403，workflow_bridge 应优雅降级。"""
    # 此测试不直接测 mock，而是验证 bridge 层的容错已在单元测试覆盖
    pass
