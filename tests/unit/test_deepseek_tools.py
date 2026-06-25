from __future__ import annotations

from agently_adapter import deepseek


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.messages = []

    def chat(self, messages, *, tools):
        self.calls += 1
        self.messages = messages
        if self.calls == 1:
            assert tools
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "unit_deepseek_tool",
                            "arguments": '{"symbol":"000021.SZ"}',
                        },
                    }
                ],
            }
        assert any(msg.get("role") == "tool" for msg in messages)
        return {
            "role": "assistant",
            "content": '{"answer":"OK","why":"used tool","sources":["tool"],"next_actions":[],"freshness_note":"","avoid":""}',
        }


def test_call_with_tools_executes_tool_loop(monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(deepseek._DeepSeekHttpClient, "from_env", classmethod(lambda cls: fake_client))

    def fake_run_tool(name, params, **kwargs):
        return {
            "ok": True,
            "tool": name,
            "data": {"echo": params},
            "elapsed_ms": 1,
        }

    monkeypatch.setattr(deepseek, "run_tool", fake_run_tool)

    result = deepseek.call_with_tools(
        {"question": "000021 怎么样"},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "unit_deepseek_tool",
                    "description": "test",
                    "parameters": {
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                },
            }
        ],
        allowed_tools=["unit_deepseek_tool"],
        user="tester",
        trace_id="trace3",
    )

    assert result is not None
    assert result["answer"] == "OK"
    assert result["trace"]["llm_tools"][0]["tool"] == "unit_deepseek_tool"
    assert result["trace"]["llm_tools"][0]["ok"] is True
    assert fake_client.calls == 2
