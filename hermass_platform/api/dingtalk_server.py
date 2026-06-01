#!/usr/bin/env python3
"""Hermass DingTalk Bot - 钉钉机器人 HTTP 服务.

Usage:
    python3 hermass_platform/api/dingtalk_server.py [--port 8080]

环境变量:
    DINGTALK_WEBHOOK_URL    钉钉机器人 Webhook 地址
"""

import json
import logging
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hermass_platform.chat.dingtalk_handler import handle_dingtalk_message, strip_at_prefix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hermass.dingtalk.server")

DEFAULT_DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK_URL", "")


def send_dingtalk_message(content: str, webhook: str | None = None) -> bool:
    """通过钉钉 Webhook 主动发送消息.

    回调回复优先使用钉钉 payload 中的 sessionWebhook；固定推送任务可通过
    DINGTALK_WEBHOOK_URL 环境变量或显式 webhook 参数发送。
    """
    url = webhook or DEFAULT_DINGTALK_WEBHOOK
    if not url:
        logger.warning("DINGTALK_WEBHOOK_URL is not configured; skip outbound message.")
        return False
    payload = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("DingTalk message sent")
        return True
    except Exception as e:
        logger.error(f"Failed to send DingTalk message: {e}")
        return False


class DingTalkCallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/dingtalk/callback":
            self._handle_dingtalk_callback()
        elif path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not_found"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"status": "ok", "service": "dingtalk"})
        else:
            self._send_json(404, {"error": "not_found"})

    def _handle_dingtalk_callback(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        challenge = data.get("challenge")
        if challenge:
            logger.info("Received DingTalk challenge verification")
            self._send_json(200, {"msgtype": "text", "text": {"content": challenge}})
            return

        msg_type = data.get("msgtype", "")
        user_message = ""
        sender_staff_id = "anonymous"
        session_webhook = ""

        if msg_type == "text":
            user_message = data.get("text", {}).get("content", "").strip()
            sender_staff_id = data.get("senderStaffId", "anonymous")
            session_webhook = data.get("sessionWebhook", "")
        else:
            event_type = data.get("EventType", "")
            if event_type == "chat:group:robot:msg:receive":
                msg_content = data.get("Content", "")
                try:
                    content_obj = json.loads(msg_content)
                    user_message = content_obj.get("text", {}).get("content", "").strip()
                except Exception:
                    user_message = str(msg_content).strip()
                sender_staff_id = data.get("SenderStaffId", "anonymous")
            else:
                if isinstance(data.get("text"), dict):
                    user_message = data.get("text", {}).get("content", "").strip()
                sender_staff_id = data.get("senderStaffId", data.get("SenderStaffId", "anonymous"))

        logger.info(
            "DingTalk callback received: sender=%s msg_type=%s has_webhook=%s message=%s",
            sender_staff_id,
            msg_type or data.get("EventType", ""),
            bool(session_webhook),
            user_message[:120] if user_message else "(empty)",
        )

        if not user_message:
            self._send_json(200, {})
            return

        cleaned_message = strip_at_prefix(user_message, robot_name="Hermass")
        try:
            reply = handle_dingtalk_message(
                user_id=sender_staff_id,
                user_message=cleaned_message or user_message,
                conversation_id="dingtalk",
                session_id=sender_staff_id,
            )
        except Exception:
            logger.exception("DingTalk handler error")
            reply = (
                "Hermass 当前未能完成这次回复。\n\n"
                "你可以试试这些问法：\n"
                "• 000021\n"
                "• 000021 怎么看\n"
                "• 深度分析 000021\n"
                "• 000021 证据卡\n"
                "• 帮助"
            )

        if session_webhook:
            self._send_reply_via_webhook(session_webhook, reply)
        else:
            logger.warning(
                "No sessionWebhook found; callback processed but no direct reply channel available."
            )

        self._send_json(200, {})

    def _send_reply_via_webhook(self, webhook_url, message):
        """通过 sessionWebhook 发送回复"""
        import urllib.request

        payload = json.dumps({"msgtype": "text", "text": {"content": message}}).encode("utf-8")

        try:
            req = urllib.request.Request(
                webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=10)
            logger.info("Reply sent via sessionWebhook")
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")

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

    parser = argparse.ArgumentParser(description="Hermass DingTalk Bot Server")
    parser.add_argument("--port", type=int, default=8081, help="HTTP port (default 8081)")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default 0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DingTalkCallbackHandler)
    logger.info(f"Hermass DingTalk Bot 启动: http://{args.host}:{args.port}")
    logger.info(f"健康检查: http://{args.host}:{args.port}/health")
    logger.info(f"钉钉回调: http://<your-domain>:{args.port}/dingtalk/callback")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
