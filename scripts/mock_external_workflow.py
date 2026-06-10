#!/usr/bin/env python3
"""本地 Mock 外部工作流服务，用于观象端到端联调冒烟。

运行：.venv/bin/python scripts/mock_external_workflow.py
默认监听 127.0.0.1:19999
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


ANSWERS = {
    "你能帮我做什么": "我是观象外部助手，可以帮你解释市场概念、整理资料、导航建议。",
    "现在能不能做": "外部工作流视角：当前市场环境需结合本地 State Cube 判断，我这里暂无实时数据。",
    "今天先看什么方向": "外部工作流视角：可关注近期政策提及的方向，但具体行业数据请以本地行业轮动画像为准。",
    "000021怎么看": "外部工作流视角：深科技属于电子制造板块，建议结合本地 MN1/W1/D1 状态综合判断。",
    "用价值分析看000021": "外部工作流视角：价值分析需查看 ROE、现金流、估值分位，本地有基本面数据时可优先参考本地。",
    "什么是state e/f": "State E/F 是 Hermass 多周期状态编码中的收缩/扩张标识，E 通常代表 Extreme（极端），F 代表 Follow（跟随）。",
    "我应该先去哪页": "建议先去首页查看当日市场快照，或前往 Watchlist 查看自选标的。",
    "解释一下低空经济这个概念": "低空经济指以低空空域为依托，以通用航空产业为主导的经济形态，包括无人机、eVTOL、低空物流等。",
}


def match_answer(message: str) -> str:
    msg = message.strip().lower().replace(" ", "").replace("/", "").replace("state", "state ")
    for key, val in ANSWERS.items():
        if key.lower().replace(" ", "").replace("/", "") in msg or msg in key.lower().replace(" ", "").replace("/", ""):
            return val
    return "外部工作流已收到你的问题，但暂无本地实时数据支撑具体判断，建议结合 Hermass 本地数据面板查看。"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 静默日志，避免刷屏
        pass

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/webhook", "/"):
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_error(400)
            return

        message = payload.get("message", "")
        guardrails = payload.get("guardrails", {})

        # 校验 guardrails（最小安全）
        required_guardrails = (
            "no_trade_execution",
            "no_position_sizing",
            "must_disclose_if_no_local_evidence",
        )
        if not all(guardrails.get(key) for key in required_guardrails):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "guardrails violated"}).encode())
            return

        answer = match_answer(message)

        response = {
            "answer": answer,
            "why": "命中 mock 外部工作流知识库。",
            "multi_cycle_view": "",
            "single_cycle_position": "",
            "avoid": "不要把外部工作流回答直接当成本地数据结论。",
            "next_actions": [
                {"label": "打开首页", "url": "/"},
            ],
            "sources": ["external_workflow", "workflow_generic"],
            "freshness_note": "Mock 外部工作流生成，暂无本地实时数据支持。",
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


if __name__ == "__main__":
    host, port = "127.0.0.1", 19999
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Mock external workflow running at http://{host}:{port}/webhook")
        server.serve_forever()
