from __future__ import annotations

from agently_adapter.workflow_bridge import WorkflowConfig, call_workflow, normalize_response
from agently_adapter.workflow_bridge import build_payload


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_normalize_response_marks_external_workflow_sources() -> None:
    result = normalize_response(
        {
            "answer": "这是外部工作流回答。",
            "why": "工作流命中知识库。",
            "sources": ["knowledge_base"],
        },
        "dify",
    )

    assert result is not None
    assert result["provider"] == "workflow_dify"
    assert result["workflow_provider"] == "dify"
    assert result["enhancement_used"] is True
    assert result["sources"][:2] == ["external_workflow", "workflow_dify"]
    assert "knowledge_base" in result["sources"]


def test_call_workflow_posts_compact_payload_and_normalizes() -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse({"output": '{"answer":"OK","why":"done"}'})

    result = call_workflow(
        "你能做什么",
        {"token": "secret", "market_data": {"phase": "observe"}},
        config=WorkflowConfig(
            provider="n8n",
            url="https://workflow.example/webhook",
            api_key="abc",
            timeout_sec=3,
        ),
        post=fake_post,
    )

    assert result is not None
    assert result["answer"] == "OK"
    assert result["provider"] == "workflow_n8n"
    assert calls[0]["headers"]["Authorization"] == "Bearer abc"
    assert "token" not in calls[0]["json"]["context"]
    assert calls[0]["json"]["guardrails"]["must_disclose_if_no_local_evidence"] is True


def test_normalize_response_rejects_empty_answer() -> None:
    assert normalize_response({"answer": ""}, "coze") is None


def test_build_payload_limits_context_and_detects_local_evidence() -> None:
    payload = build_payload(
        "你能做什么",
        {
            "market_data": {"phase": "observe"},
            "recent_turns": [{"role": "user", "message": "secret"}],
            "value_call": lambda: None,
            "api_key": "should_not_leak",
        },
    )

    assert payload["message"] == "你能做什么"
    assert payload["local_evidence_available"] is True
    assert "recent_turns" not in payload["context"]
    assert "value_call" not in payload["context"]
    assert "api_key" not in payload["context"]
    assert payload["context"]["market_data"]["phase"] == "observe"


def test_normalize_response_handles_common_dify_coze_n8n_shapes() -> None:
    dify = normalize_response(
        {
            "data": {
                "answer": "Dify answer",
                "why": "来自 Dify。",
                "sources": ["daily_snapshot", "knowledge_base"],
            }
        },
        "dify",
    )
    assert dify is not None
    assert dify["answer"] == "Dify answer"
    assert dify["provider"] == "workflow_dify"
    assert "daily_snapshot" not in dify["sources"]
    assert "knowledge_base" in dify["sources"]

    coze = normalize_response(
        {
            "messages": [
                {"type": "assistant", "content": "Coze answer"},
                {"type": "assistant", "content": ""},
            ],
            "reason": "来自 Coze。",
        },
        "coze",
    )
    assert coze is not None
    assert coze["answer"] == "Coze answer"
    assert coze["why"] == "来自 Coze。"
    assert coze["provider"] == "workflow_coze"

    n8n = normalize_response(
        {
            "output": '{"answer":"N8N answer","why":"来自 N8N。","next_actions":[{"title":"打开页面","href":"/research"}],"sources":["state_cube","external_note"]}'
        },
        "n8n",
    )
    assert n8n is not None
    assert n8n["answer"] == "N8N answer"
    assert n8n["next_actions"] == [{"label": "打开页面", "url": "/research"}]
    assert "state_cube" not in n8n["sources"]
    assert "external_note" in n8n["sources"]


# ------------------------------------------------------------------
# 8 个覆盖问题类型测试（2026-06-09 任务扩展）
# ------------------------------------------------------------------

def test_build_payload_covers_eight_question_types() -> None:
    """验证 8 个覆盖问题的 payload 构建正确，且 guardrails 始终注入。"""
    from agently_adapter.workflow_bridge import build_payload

    questions = [
        ("泛问题", "你能帮我做什么"),
        ("市场问题", "现在能不能做"),
        ("行业问题", "今天先看什么方向"),
        ("个股问题", "000021 怎么看"),
        ("基本面问题", "用价值分析看 000021"),
        ("教学问题", "什么是 State E/F"),
        ("导航问题", "我应该先去哪页"),
        ("无本地数据问题", "解释一下低空经济这个概念"),
    ]

    for _label, msg in questions:
        payload = build_payload(msg, {"current_page": "/", "mode": "chat"})
        assert payload["message"] == msg
        assert payload["query"] == msg
        assert payload["guardrails"]["no_trade_execution"] is True
        assert payload["guardrails"]["must_disclose_if_no_local_evidence"] is True
        assert "response_contract" in payload


def test_normalize_response_does_not_fake_local_sources() -> None:
    """外部工作流伪造 daily_snapshot/research_evidence 时，归一化后应过滤掉。"""
    from agently_adapter.workflow_bridge import normalize_response

    result = normalize_response(
        {
            "answer": "某回答",
            "sources": ["daily_snapshot", "research_evidence", "knowledge_base"],
        },
        "dify",
    )
    assert result is not None
    # 前两个固定为外部标识
    assert result["sources"][:2] == ["external_workflow", "workflow_dify"]
    # 原始 sources 中不应包含本地源伪造
    assert "daily_snapshot" not in result["sources"]
    assert "research_evidence" not in result["sources"]
    assert "knowledge_base" in result["sources"]


def test_normalize_response_coze_nested_data_format() -> None:
    """Coze 典型嵌套 data 格式兼容。"""
    from agently_adapter.workflow_bridge import normalize_response

    result = normalize_response(
        {
            "data": {
                "answer": "Coze 回答",
                "why": "嵌套在 data 里",
                "sources": ["external_workflow", "workflow_coze"],
            }
        },
        "coze",
    )
    assert result is not None
    assert result["answer"] == "Coze 回答"
    assert result["provider"] == "workflow_coze"


def test_normalize_response_generic_json_string_output() -> None:
    """Generic 平台返回 JSON 字符串在 output/text 字段时兼容。"""
    from agently_adapter.workflow_bridge import normalize_response

    result = normalize_response(
        {
            "output": '{"answer":"字符串内JSON","why":"嵌套"}',
        },
        "generic",
    )
    assert result is not None
    assert result["answer"] == "字符串内JSON"
    assert result["why"] == "嵌套"


def test_normalize_response_messages_array_format() -> None:
    """OpenAI-like messages 数组格式兼容。"""
    from agently_adapter.workflow_bridge import normalize_response

    result = normalize_response(
        {
            "messages": [
                {"role": "user", "content": "用户问题"},
                {"role": "assistant", "content": "助手回答"},
            ]
        },
        "n8n",
    )
    assert result is not None
    assert result["answer"] == "助手回答"
    assert result["provider"] == "workflow_n8n"


def test_call_workflow_with_dify_config() -> None:
    """Dify 配置下调用，验证 header 和 provider 标记。"""
    from agently_adapter.workflow_bridge import WorkflowConfig, call_workflow

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse({"answer": "Dify 返回", "sources": ["dify_kb"]})

    result = call_workflow(
        "今天先看什么方向",
        {"current_page": "/"},
        config=WorkflowConfig(
            provider="dify",
            url="https://api.dify.ai/v1/chat-messages",
            api_key="dify-secret",
            timeout_sec=8,
        ),
        post=fake_post,
    )

    assert result is not None
    assert result["answer"] == "Dify 返回"
    assert result["provider"] == "workflow_dify"
    assert calls[0]["headers"]["Authorization"] == "Bearer dify-secret"
    assert calls[0]["timeout"] == 8


def test_call_workflow_with_coze_config_custom_header() -> None:
    """Coze 使用自定义 header（x-api-key）时正确构造。"""
    from agently_adapter.workflow_bridge import WorkflowConfig, call_workflow

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse({"data": {"answer": "Coze 回答"}})

    result = call_workflow(
        "解释一下低空经济",
        {},
        config=WorkflowConfig(
            provider="coze",
            url="https://api.coze.cn/open_api/v2/chat",
            api_key="coze-token",
            auth_header="x-api-key",
            auth_scheme="",
            timeout_sec=10,
        ),
        post=fake_post,
    )

    assert result is not None
    assert result["answer"] == "Coze 回答"
    assert calls[0]["headers"]["x-api-key"] == "coze-token"
    assert "Authorization" not in calls[0]["headers"]
