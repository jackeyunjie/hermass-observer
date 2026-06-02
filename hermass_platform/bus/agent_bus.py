#!/usr/bin/env python3
"""AgentBus — 文件队列 pub/sub 消息总线。

实现 Agent 间异步通信：
  - 消息格式：JSON（含 UUID、优先级、payload）
  - 6 种标准消息类型
  - 文件队列传输：写入 outputs/agent_bus/outbox/
  - 订阅过滤：Agent 只接收自己订阅的消息类型
  - 延迟 < 500ms

用法（作为模块导入）：
  from hermass_platform.bus.agent_bus import AgentBus

  bus = AgentBus()
  bus.subscribe("contraction_observer", ["contraction_extreme", "market_phase_change"])
  bus.publish("contraction_observer", "strategy_advisor", "contraction_extreme",
              payload={"stock_code": "000001", "squeeze_score": 85}, priority=1)

  messages = bus.poll("strategy_advisor")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("agent_bus")

# ── 标准消息类型 ──────────────────────────────────────────────
MESSAGE_TYPES = {
    "contraction_extreme": "收缩观测发现极致收缩，通知策略 Agent 提高优先级",
    "market_phase_change": "市场阶段转换，通知所有 Agent 重新评估策略适配",
    "false_breakout": "假突破标记，通知风控 Agent 暂停仓位建议",
    "weight_adjusted": "因子权重修正，通知校验 Agent 记录",
    "review_needed": "分歧超阈值，通知人类审阅",
    "data_stale": "数据过期，通知所有 Agent 降级运行",
}

# ── 各 topic 的 payload JSON schema（required 字段 + 类型） ──
PAYLOAD_SCHEMAS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "contraction_extreme": {
        "stock_code": str,
        "squeeze_score": (int, float),
        "timeframe": str,
    },
    "market_phase_change": {
        "old_phase": str,
        "new_phase": str,
    },
    "false_breakout": {
        "stock_code": str,
        "breakout_date": str,
    },
    "weight_adjusted": {
        "factor_name": str,
        "old_weight": (int, float),
        "new_weight": (int, float),
    },
    "review_needed": {
        "subject": str,
    },
    "data_stale": {
        "table_name": str,
        "last_updated": str,
    },
}


def _validate_payload(topic: str, payload: dict) -> list[str]:
    """校验 payload 是否符合该 topic 的 schema。

    Returns:
        错误信息列表，空列表 = 校验通过
    """
    schema = PAYLOAD_SCHEMAS.get(topic)
    if schema is None:
        return []

    errors: list[str] = []
    for field, expected_type in schema.items():
        if field not in payload:
            errors.append(f"缺少必填字段: {field}")
        elif not isinstance(payload[field], expected_type):
            errors.append(
                f"字段 {field} 类型错误: 期望 {expected_type}, "
                f"实际 {type(payload[field]).__name__}"
            )
    return errors


DEFAULT_OUTBOX = ROOT / "outputs" / "agent_bus" / "outbox"


class AgentBus:
    """文件队列 pub/sub 消息总线。"""

    def __init__(self, outbox_dir: Optional[Path] = None):
        self.outbox_dir = outbox_dir or DEFAULT_OUTBOX
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

        # 订阅注册表：{agent_id: set(topics)}
        self._subscriptions: dict[str, set[str]] = {}

        # 加载持久化的订阅信息
        self._load_subscriptions()

    # ── 订阅管理 ──────────────────────────────────────────────

    def subscribe(self, agent_id: str, topics: list[str]) -> None:
        """注册 Agent 的订阅。

        Args:
            agent_id: 接收方 Agent ID
            topics: 订阅的消息类型列表
        """
        valid_topics = set(topics) & set(MESSAGE_TYPES.keys())
        invalid = set(topics) - valid_topics
        if invalid:
            log.warning("忽略未知消息类型: %s", invalid)

        self._subscriptions[agent_id] = valid_topics
        self._save_subscriptions()
        log.info("订阅注册: %s -> %s", agent_id, list(valid_topics))

    def unsubscribe(self, agent_id: str) -> None:
        """取消 Agent 的所有订阅。"""
        self._subscriptions.pop(agent_id, None)
        self._save_subscriptions()
        log.info("取消订阅: %s", agent_id)

    def get_subscriptions(self, agent_id: str = "") -> dict[str, list[str]]:
        """查询订阅信息。"""
        if agent_id:
            topics = self._subscriptions.get(agent_id, set())
            return {agent_id: sorted(topics)}
        return {k: sorted(v) for k, v in self._subscriptions.items()}

    # ── 发布消息 ──────────────────────────────────────────────

    def publish(
        self,
        from_agent: str,
        to_agent: str,
        topic: str,
        payload: dict,
        priority: int = 5,
        requires_response: bool = False,
    ) -> dict:
        """发布一条消息到文件队列。

        Args:
            from_agent: 发送方 Agent ID
            to_agent: 接收方 Agent ID（"*" 表示广播给所有订阅者）
            topic: 消息类型（必须是 MESSAGE_TYPES 之一）
            payload: 消息内容
            priority: 优先级（1=最高，9=最低）
            requires_response: 是否需要接收方回复

        Returns:
            消息字典（含 message_id）
        """
        if topic not in MESSAGE_TYPES:
            raise ValueError(f"未知消息类型: {topic}，可选: {list(MESSAGE_TYPES.keys())}")

        # JSON schema 校验
        schema_errors = _validate_payload(topic, payload)
        if schema_errors:
            raise ValueError(
                f"payload 校验失败 [{topic}]: {'; '.join(schema_errors)}"
            )

        message = {
            "message_id": str(uuid.uuid4()),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "topic": topic,
            "priority": max(1, min(9, priority)),
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requires_response": requires_response,
        }

        self._write_message(message)
        log.info(
            "发布消息: %s [%s] %s -> %s (priority=%d)",
            message["message_id"][:8],
            topic,
            from_agent,
            to_agent,
            priority,
        )
        return message

    def publish_broadcast(
        self,
        from_agent: str,
        topic: str,
        payload: dict,
        priority: int = 5,
    ) -> list[dict]:
        """广播消息给所有订阅了该 topic 的 Agent。

        Returns:
            发送的消息列表
        """
        messages = []
        for agent_id, topics in self._subscriptions.items():
            if agent_id == from_agent:
                continue  # 不发给自己
            if topic in topics:
                msg = self.publish(from_agent, agent_id, topic, payload, priority)
                messages.append(msg)

        if not messages:
            log.info("广播 [%s] 无订阅者", topic)

        return messages

    # ── 接收消息 ──────────────────────────────────────────────

    def poll(self, agent_id: str, max_messages: int = 100) -> list[dict]:
        """轮询接收消息。

        读取 outbox 中发往该 Agent 的消息，读后删除文件。

        Args:
            agent_id: 接收方 Agent ID
            max_messages: 单次最多读取数量

        Returns:
            消息列表（按优先级排序）
        """
        messages = []

        # 扫描 outbox 目录
        for msg_file in sorted(self.outbox_dir.glob("*.json")):
            if len(messages) >= max_messages:
                break

            try:
                with open(msg_file, "r", encoding="utf-8") as f:
                    msg = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                log.warning("读取消息失败 %s: %s", msg_file, e)
                continue

            # 检查接收方
            if msg.get("to_agent") != agent_id and msg.get("to_agent") != "*":
                continue

            # 检查订阅
            subscribed_topics = self._subscriptions.get(agent_id, set())
            if msg.get("topic") not in subscribed_topics:
                continue

            messages.append(msg)

            # 读后删除（at-least-once delivery）
            try:
                msg_file.unlink()
            except OSError:
                pass

        # 按优先级排序（priority 数字越小越优先）
        messages.sort(key=lambda m: m.get("priority", 5))

        if messages:
            log.info("Agent %s 收到 %d 条消息", agent_id, len(messages))

        return messages

    def peek(self, agent_id: str, max_messages: int = 10) -> list[dict]:
        """预览消息（不删除）。"""
        messages = []

        for msg_file in sorted(self.outbox_dir.glob("*.json")):
            if len(messages) >= max_messages:
                break

            try:
                with open(msg_file, "r", encoding="utf-8") as f:
                    msg = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            if msg.get("to_agent") in (agent_id, "*"):
                messages.append(msg)

        messages.sort(key=lambda m: m.get("priority", 5))
        return messages

    # ── 队列管理 ──────────────────────────────────────────────

    def queue_size(self) -> int:
        """队列中的消息数量。"""
        return len(list(self.outbox_dir.glob("*.json")))

    def clear_queue(self, agent_id: str = "") -> int:
        """清空队列。指定 agent_id 时只清除该 Agent 的消息。"""
        cleared = 0
        for msg_file in self.outbox_dir.glob("*.json"):
            if agent_id:
                try:
                    with open(msg_file, "r", encoding="utf-8") as f:
                        msg = json.load(f)
                    if msg.get("to_agent") != agent_id:
                        continue
                except (json.JSONDecodeError, IOError):
                    pass

            try:
                msg_file.unlink()
                cleared += 1
            except OSError:
                pass

        log.info("清除 %d 条消息", cleared)
        return cleared

    # ── 内部方法 ──────────────────────────────────────────────

    def _write_message(self, message: dict) -> None:
        """将消息写入 outbox 文件。"""
        filename = (
            f"{message['timestamp'][:19].replace(':', '')}_"
            f"{message['priority']}_"
            f"{message['message_id'][:8]}.json"
        )
        filepath = self.outbox_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(message, f, ensure_ascii=False, indent=2)

    def _subscriptions_file(self) -> Path:
        return self.outbox_dir.parent / "subscriptions.json"

    def _save_subscriptions(self) -> None:
        """持久化订阅信息。"""
        data = {k: sorted(v) for k, v in self._subscriptions.items()}
        sub_file = self._subscriptions_file()
        sub_file.parent.mkdir(parents=True, exist_ok=True)
        with open(sub_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_subscriptions(self) -> None:
        """从文件加载订阅信息。"""
        sub_file = self._subscriptions_file()
        if not sub_file.exists():
            return

        try:
            with open(sub_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._subscriptions = {k: set(v) for k, v in data.items()}
            log.info("加载订阅: %d 个 Agent", len(self._subscriptions))
        except (json.JSONDecodeError, IOError) as e:
            log.warning("加载订阅失败: %s", e)


# ── 便捷函数 ──────────────────────────────────────────────────

def create_bus(outbox_dir: Optional[Path] = None) -> AgentBus:
    """创建 AgentBus 实例。"""
    return AgentBus(outbox_dir)


def publish_contraction_extreme(
    bus: AgentBus,
    stock_code: str,
    squeeze_score: int,
    timeframe: str = "D1",
    details: dict | None = None,
) -> dict:
    """发布极致收缩事件。"""
    payload = {
        "stock_code": stock_code,
        "squeeze_score": squeeze_score,
        "timeframe": timeframe,
    }
    if details:
        payload.update(details)

    return bus.publish(
        from_agent="contraction_observer",
        to_agent="*",
        topic="contraction_extreme",
        payload=payload,
        priority=1,
    )


def publish_market_phase_change(
    bus: AgentBus,
    old_phase: str,
    new_phase: str,
    reason: str = "",
) -> list[dict]:
    """发布市场阶段变更广播。"""
    return bus.publish_broadcast(
        from_agent="market_analyst",
        topic="market_phase_change",
        payload={
            "old_phase": old_phase,
            "new_phase": new_phase,
            "reason": reason,
        },
        priority=1,
    )


def publish_false_breakout(
    bus: AgentBus,
    stock_code: str,
    breakout_date: str,
    reason: str = "",
) -> dict:
    """发布假突破标记。"""
    return bus.publish(
        from_agent="contraction_observer",
        to_agent="risk_guardian",
        topic="false_breakout",
        payload={
            "stock_code": stock_code,
            "breakout_date": breakout_date,
            "reason": reason,
        },
        priority=2,
    )


def publish_review_needed(
    bus: AgentBus,
    from_agent: str,
    subject: str,
    details: dict | None = None,
) -> dict:
    """发布人类审阅请求。"""
    payload = {"subject": subject}
    if details:
        payload.update(details)

    return bus.publish(
        from_agent=from_agent,
        to_agent="human_reviewer",
        topic="review_needed",
        payload=payload,
        priority=1,
        requires_response=True,
    )


def publish_weight_adjusted(
    bus: AgentBus,
    from_agent: str,
    factor_name: str,
    old_weight: float,
    new_weight: float,
    reason: str = "",
) -> dict:
    """发布因子权重修正事件。"""
    payload = {
        "factor_name": factor_name,
        "old_weight": old_weight,
        "new_weight": new_weight,
    }
    if reason:
        payload["reason"] = reason

    return bus.publish(
        from_agent=from_agent,
        to_agent="*",
        topic="weight_adjusted",
        payload=payload,
        priority=3,
    )


def publish_data_stale(
    bus: AgentBus,
    from_agent: str,
    table_name: str,
    last_updated: str,
    reason: str = "",
) -> list[dict]:
    """发布数据过期广播。"""
    payload = {
        "table_name": table_name,
        "last_updated": last_updated,
    }
    if reason:
        payload["reason"] = reason

    return bus.publish_broadcast(
        from_agent=from_agent,
        topic="data_stale",
        payload=payload,
        priority=2,
    )


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="AgentBus 消息总线 CLI")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="查看队列状态")

    # subscriptions
    sub.add_parser("subscriptions", help="查看订阅信息")

    # clear
    clear_parser = sub.add_parser("clear", help="清空队列")
    clear_parser.add_argument("--agent", type=str, default="", help="指定 Agent ID")

    # test — 发送测试消息
    test_parser = sub.add_parser("test", help="发送测试消息")
    test_parser.add_argument("--topic", type=str, default="contraction_extreme")
    test_parser.add_argument("--from-agent", type=str, default="test")
    test_parser.add_argument("--to-agent", type=str, default="*")

    args = parser.parse_args()

    bus = AgentBus()

    if args.command == "status":
        print(f"Outbox 目录: {bus.outbox_dir}")
        print(f"队列消息数: {bus.queue_size()}")

    elif args.command == "subscriptions":
        subs = bus.get_subscriptions()
        print(json.dumps(subs, indent=2, ensure_ascii=False))

    elif args.command == "clear":
        n = bus.clear_queue(args.agent)
        print(f"已清除 {n} 条消息")

    elif args.command == "test":
        msg = bus.publish(
            from_agent=args.from_agent,
            to_agent=args.to_agent,
            topic=args.topic,
            payload={"test": True, "timestamp": time.time()},
            priority=5,
        )
        print(f"已发送测试消息: {msg['message_id']}")

    else:
        parser.print_help()
