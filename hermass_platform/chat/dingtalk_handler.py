"""Hermass DingTalk Bot - 钉钉消息处理入口.

直接复用 lark_handler 的业务逻辑，只做平台适配。
"""

import logging
import re

from hermass_platform.chat.lark_handler import handle_lark_message

logger = logging.getLogger("hermass.dingtalk.handler")


def _get_dingtalk_help_message() -> str:
    return (
        "Hermass 钉钉助手\n\n"
        "你现在可以直接这样问：\n"
        "1. 个股快速研究\n"
        "   - 000021 怎么看\n"
        "   - 000021 快速研究\n\n"
        "2. 个股深度研究\n"
        "   - 深度分析 000021\n"
        "   - 000021 标准版研究\n"
        "   - 000021 完整版研究\n\n"
        "3. 证据与来源\n"
        "   - 000021 证据卡\n"
        "   - 000021 数据来源\n\n"
        "4. 市场与行业\n"
        "   - 市场怎么样\n"
        "   - 电子行业怎么样\n"
        "   - 医药行业怎么样\n\n"
        "5. 策略与风险\n"
        "   - 有什么好信号\n"
        "   - 000001 止损\n"
        "   - 我的持仓有什么风险\n\n"
        "6. 学习与解释\n"
        "   - 什么是 State\n"
        "   - VCP 是什么\n\n"
        "说明：\n"
        "- 默认回复基于 A 股研究链路\n"
        "- 结论仅供研究参考，不构成投资建议"
    )


def handle_dingtalk_message(
    user_id: str,
    user_message: str,
    conversation_id: str = "",
    session_id: str = "",
) -> str:
    """处理钉钉消息，复用飞书 Bot 的完整业务链路.

    Args:
        user_id: 钉钉用户的 staffId / openId
        user_message: 用户发送的文本（已去除 @Bot 前缀）
        conversation_id: 钉钉会话 ID（群聊/单聊）
        session_id: 会话标识（可选）

    Returns:
        纯文本回复内容
    """
    normalized = user_message.strip()
    if normalized in {"帮助", "help", "?", "功能", "菜单"}:
        return _get_dingtalk_help_message()

    if re.fullmatch(r"\d{6}", normalized):
        normalized = f"{normalized} 怎么看"
    else:
        match = re.fullmatch(r"(?:行情|价格|quote)\s+(\d{6})", normalized, flags=re.IGNORECASE)
        if match:
            normalized = f"{match.group(1)} 怎么看"

    # 钉钉和飞书的业务逻辑完全一致，直接透传
    return handle_lark_message(
        user_id=user_id,
        user_message=normalized,
        chat_id=conversation_id,
        session_id=session_id,
    )


def strip_at_prefix(text: str, robot_name: str = "") -> str:
    """去除钉钉消息中的 @机器人 前缀.

    钉钉文本消息中 @机器人 的格式通常为:
      @机器人名称 实际消息
    或富文本中的 at 标签。
    """
    # 去除 @机器人名称 前缀
    if robot_name:
        text = re.sub(rf'@{re.escape(robot_name)}\s*', '', text)
    # 通用去除 @任意词 前缀（保留后续内容）
    text = re.sub(r'@\S+\s*', '', text)
    return text.strip()
