#!/usr/bin/env python3
"""Hermass Lark Bot - 飞书事件回调 HTTP 服务.

Usage:
    python3 hermass_platform/api/lark_server.py [--port 8080]

环境变量:
    LARK_VERIFICATION_TOKEN    飞书验证 Token
    LARK_APP_SECRET            飞书签名密钥 (可选)
"""

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hermass.lark.server")

VERIFICATION_TOKEN = os.environ.get("LARK_VERIFICATION_TOKEN", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")


class LarkCallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/lark/callback":
            self._handle_lark_callback()
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"status": "ok", "agents": 7, "tests": 383})
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_lark_callback(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        challenge = data.get("challenge")
        if challenge:
            logger.info("Received URL verification challenge")
            self._send_json(200, {"challenge": challenge})
            return

        token = data.get("token", "")
        # 兼容新旧版飞书：旧版带 token 需校验，新版不带 token 直接放行
        if VERIFICATION_TOKEN and token and token != VERIFICATION_TOKEN:
            logger.warning(f"Token mismatch: received={token[:8]}..., expected={VERIFICATION_TOKEN[:8]}...")
            self._send_json(200, {})
            return

        # 兼容飞书 schema 1.0 / 2.0
        schema = data.get("schema", "")
        if schema == "2.0":
            header = data.get("header", {})
            event_type = header.get("event_type", "")
            logger.info(f"Received event: schema=2.0, event_type={event_type}")
        else:
            event_type = data.get("type", "")
            logger.info(f"Received event: type={event_type}")

        if event_type == "url_verification":
            self._send_json(200, {"challenge": challenge})
            return

        # 支持多种事件类型格式
        valid_event_types = ("event_callback", "im.message.receive_v1", "message")
        if event_type not in valid_event_types:
            logger.info(f"DEBUG: skip event_type={event_type}, not in {valid_event_types}")
            self._send_json(200, {})
            return

        event = data.get("event", {})
        msg_type = event.get("message", {}).get("message_type", "")
        message_id = event.get("message", {}).get("message_id", "")

        # DEBUG: 打印完整事件结构（首次排查后删除）
        logger.info(f"DEBUG event structure: msg_type={msg_type}, message_id={message_id}")

        if msg_type != "text":
            logger.info(f"DEBUG: skip non-text message, msg_type={msg_type}")
            self._send_json(200, {})
            return

        raw_content = event.get("message", {}).get("content", "{}")
        logger.info(f"DEBUG raw_content: {raw_content[:200]}")
        try:
            content_dict = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            user_message_raw = content_dict.get("text", "").strip()
        except (json.JSONDecodeError, AttributeError) as e:
            logger.info(f"DEBUG content parse error: {e}")
            user_message_raw = ""

        import re

        user_message = re.sub(r"@\S+\s*", "", user_message_raw).strip()
        logger.info(f"DEBUG parsed user_message: '{user_message}'")

        if not user_message:
            logger.info("DEBUG: empty user_message after filter, skip")
            self._send_json(200, {})
            return

        open_id = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
        chat_id = event.get("message", {}).get("chat_id", "")
        if not open_id:
            open_id = event.get("sender", {}).get("sender_id", {}).get("user_id", "anonymous")

        logger.info(f"Message from {open_id[:12]}... in chat {chat_id[:12]}...: {user_message[:80]}")

        try:
            from hermass_platform.chat.lark_handler import handle_lark_message

            reply = handle_lark_message(
                user_id=open_id,
                user_message=user_message,
                chat_id=chat_id,
            )
        except Exception as e:
            logger.exception("Handler error")
            reply = "系统处理请求时出现异常，请稍后重试。"

        response = {
            "msg_type": "text",
            "content": {"text": reply},
        }
        self._send_json(200, response)

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Hermass Lark Bot Server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0)")
    args = parser.parse_args()

    if not VERIFICATION_TOKEN:
        logger.warning("LARK_VERIFICATION_TOKEN 未设置。请在飞书开发者后台获取并设置环境变量。")
        logger.warning("  export LARK_VERIFICATION_TOKEN=your_token_here")

    server = HTTPServer((args.host, args.port), LarkCallbackHandler)
    logger.info(f"Hermass Lark Bot 启动: http://{args.host}:{args.port}")
    logger.info(f"飞书回调地址: http://<your-domain>:{args.port}/lark/callback")
    logger.info(f"健康检查: http://{args.host}:{args.port}/health")
    logger.info(f"Verification Token: {'已设置' if VERIFICATION_TOKEN else '未设置'}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
