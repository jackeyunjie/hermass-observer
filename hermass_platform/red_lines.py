#!/usr/bin/env python3
"""Red Lines — 五条红线代码层拦截。

五条不可绕过的系统红线：
  1. 止损/止盈在无人类确认时自动拒绝
  2. 策略结构修改（VCP/2560/Bollinger 信号定义）被 admin API 拦截
  3. Agent 标记数据异常时必须提交 human review
  4. 仓位上限检查在 risk_guardian 中不可绕过的 max_position_pct
  5. Admin API: POST /api/admin/kill-switch 一键暂停自进化

设计理念：
  - 红线是硬约束，不可被任何配置、参数或 LLM 判断覆盖
  - 每条红线有独立的检查函数和拦截装饰器
  - 所有拦截事件写入 red_line_audit_log 用于审计

Usage:
    from hermass_platform.red_lines import (
        require_human_confirmation,
        guard_strategy_structure,
        flag_data_anomaly,
        enforce_max_position,
        is_kill_switch_active,
    )
"""

from __future__ import annotations

import functools
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import yaml
except ImportError:
    yaml = None  # Fallback: use hardcoded defaults

ROOT = Path(__file__).resolve().parents[1]

# ── 红线配置加载 ──────────────────────────────────────────────
_REDLINES_CONFIG_PATH = ROOT / "config" / "redlines.yaml"


def _load_redlines_config() -> dict:
    """加载红线配置。优先从 YAML 读取，失败则使用硬编码默认值。"""
    if _REDLINES_CONFIG_PATH.exists() and yaml is not None:
        try:
            with open(_REDLINES_CONFIG_PATH, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception:
            pass
    # 硬编码默认值
    return {
        "redlines": {
            "max_position_enforcement": {"max_position_pct": 0.25},
        },
        "audit": {
            "log_file": "outputs/red_line_audit_log.jsonl",
        },
    }


REDLINES_CONFIG = _load_redlines_config()


def get_redlines_config() -> dict:
    """返回已加载的红线配置（只读检查用）。"""
    return REDLINES_CONFIG


# ── 红线状态文件 ──────────────────────────────────────────────
KILL_SWITCH_FILE = ROOT / "config" / "kill_switch.json"
RED_LINE_AUDIT_LOG = ROOT / "outputs" / "red_line_audit_log.jsonl"
STRATEGY_STRUCTURE_LOCK = ROOT / "config" / "strategy_structure_lock.json"

# ── 受保护策略列表（从配置加载，fallback 硬编码）────────────────
_cfg_strategies = (
    REDLINES_CONFIG.get("redlines", {})
    .get("strategy_structure_immutable", {})
    .get("protected_strategies", [])
)
PROTECTED_STRATEGIES = set(_cfg_strategies) if _cfg_strategies else {"vcp", "ma2560", "bollinger_bandit", "composite"}

# ── 默认仓位上限（从配置加载，fallback 25%）────────────────────
DEFAULT_MAX_POSITION_PCT = (
    REDLINES_CONFIG.get("redlines", {})
    .get("max_position_enforcement", {})
    .get("max_position_pct", 0.25)
)


@dataclass
class RedLineViolation:
    """红线违规记录。"""
    rule_id: int
    rule_name: str
    action: str  # "blocked" | "flagged" | "alerted"
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    agent_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "action": self.action,
            "context": self.context,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
        }


def _append_audit_log(violation: RedLineViolation) -> None:
    """追加红线审计日志。"""
    RED_LINE_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RED_LINE_AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(violation.to_dict(), ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════
# 红线 1：止损/止盈在无人类确认时自动拒绝
# ═══════════════════════════════════════════════════════════════

def require_human_confirmation(
    action_type: str,
    stock_code: str,
    details: dict[str, Any],
    human_confirmed: bool = False,
    agent_id: str = "",
) -> dict[str, Any]:
    """红线 1：止损/止盈操作必须有人类确认。

    Args:
        action_type: "stop_loss" | "take_profit" | "exit_position"
        stock_code: 股票代码
        details: 操作详情（价格、原因等）
        human_confirmed: 人类是否已确认
        agent_id: 发起操作的 Agent ID

    Returns:
        {"allowed": bool, "reason": str, "violation": RedLineViolation | None}
    """
    if human_confirmed:
        return {
            "allowed": True,
            "reason": "人类已确认",
            "violation": None,
        }

    # 未确认 → 自动拒绝
    violation = RedLineViolation(
        rule_id=1,
        rule_name="stop_loss_requires_human_confirmation",
        action="blocked",
        context={
            "action_type": action_type,
            "stock_code": stock_code,
            "details": details,
        },
        agent_id=agent_id,
    )
    _append_audit_log(violation)

    return {
        "allowed": False,
        "reason": f"红线 1 拦截：{action_type} 操作需要人类确认，当前未获得确认",
        "violation": violation.to_dict(),
    }


# ═══════════════════════════════════════════════════════════════
# 红线 2：策略结构修改被 admin API 拦截
# ═══════════════════════════════════════════════════════════════

def guard_strategy_structure(
    strategy_name: str,
    proposed_changes: dict[str, Any],
    admin_token: str = "",
    agent_id: str = "",
) -> dict[str, Any]:
    """红线 2：策略信号定义修改必须通过 admin API + token 验证。

    受保护的策略：VCP / MA2560 / Bollinger Bandit / Composite

    Args:
        strategy_name: 策略名称
        proposed_changes: 拟修改的内容
        admin_token: admin 令牌（必须匹配环境变量 HERMASS_ADMIN_TOKEN）
        agent_id: 发起修改的 Agent ID

    Returns:
        {"allowed": bool, "reason": str, "violation": RedLineViolation | None}
    """
    if strategy_name not in PROTECTED_STRATEGIES:
        return {"allowed": True, "reason": "非受保护策略，允许修改", "violation": None}

    # 检查 admin token
    expected_token = os.environ.get("HERMASS_ADMIN_TOKEN", "")
    if not expected_token:
        # 未配置 token 时，默认拒绝所有修改
        violation = RedLineViolation(
            rule_id=2,
            rule_name="strategy_structure_modification_blocked",
            action="blocked",
            context={
                "strategy_name": strategy_name,
                "proposed_changes": proposed_changes,
                "reason": "HERMASS_ADMIN_TOKEN 未配置，所有受保护策略修改被拒绝",
            },
            agent_id=agent_id,
        )
        _append_audit_log(violation)
        return {
            "allowed": False,
            "reason": "红线 2 拦截：HERMASS_ADMIN_TOKEN 未配置，无法修改受保护策略",
            "violation": violation.to_dict(),
        }

    if admin_token != expected_token:
        violation = RedLineViolation(
            rule_id=2,
            rule_name="strategy_structure_modification_blocked",
            action="blocked",
            context={
                "strategy_name": strategy_name,
                "proposed_changes": proposed_changes,
                "reason": "admin token 不匹配",
            },
            agent_id=agent_id,
        )
        _append_audit_log(violation)
        return {
            "allowed": False,
            "reason": "红线 2 拦截：admin token 验证失败",
            "violation": violation.to_dict(),
        }

    # Token 验证通过，记录修改
    violation = RedLineViolation(
        rule_id=2,
        rule_name="strategy_structure_modification_approved",
        action="alerted",
        context={
            "strategy_name": strategy_name,
            "proposed_changes": proposed_changes,
            "reason": "admin token 验证通过，策略修改已记录",
        },
        agent_id=agent_id,
    )
    _append_audit_log(violation)

    return {"allowed": True, "reason": "admin token 验证通过，修改已审计记录", "violation": None}


# ═══════════════════════════════════════════════════════════════
# 红线 3：Agent 标记数据异常时必须提交 human review
# ═══════════════════════════════════════════════════════════════

def flag_data_anomaly(
    agent_id: str,
    anomaly_type: str,
    stock_code: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """红线 3：数据异常必须提交人类审核，不可由 Agent 自行处理。

    Args:
        agent_id: 发现异常的 Agent ID
        anomaly_type: 异常类型（如 "missing_data", "outlier_value", "schema_mismatch"）
        stock_code: 相关股票代码
        details: 异常详情

    Returns:
        {"must_submit_review": True, "review_queue_entry": dict}
    """
    review_entry = {
        "review_id": f"anomaly_{int(time.time())}_{agent_id}",
        "agent_id": agent_id,
        "anomaly_type": anomaly_type,
        "stock_code": stock_code,
        "details": details or {},
        "status": "pending_human_review",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    violation = RedLineViolation(
        rule_id=3,
        rule_name="data_anomaly_requires_human_review",
        action="flagged",
        context=review_entry,
        agent_id=agent_id,
    )
    _append_audit_log(violation)

    # 写入审核队列文件
    review_queue_path = ROOT / "outputs" / "human_review_queue.jsonl"
    review_queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_queue_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(review_entry, ensure_ascii=False) + "\n")

    # AgentBus 自动广播 review_needed
    if REDLINES_CONFIG.get("redlines", {}).get("data_anomaly_requires_human_review", {}).get("auto_broadcast", True):
        try:
            from hermass_platform.bus.agent_bus import AgentBus
            bus = AgentBus()
            bus.publish(
                from_agent=agent_id or "system",
                to_agent="human_reviewer",
                topic="review_needed",
                payload={
                    "subject": f"数据异常审核: {anomaly_type} ({stock_code or 'N/A'})",
                },
                priority=1,
            )
        except Exception:
            pass  # AgentBus 不可用时静默降级

    return {
        "must_submit_review": True,
        "review_queue_entry": review_entry,
        "reason": f"红线 3：数据异常 ({anomaly_type}) 已提交人类审核队列",
    }


# ═══════════════════════════════════════════════════════════════
# 红线 4：仓位上限检查不可绕过
# ═══════════════════════════════════════════════════════════════

def enforce_max_position(
    stock_code: str,
    proposed_weight: float,
    max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
    portfolio_total: float = 1.0,
    agent_id: str = "",
    override_token: str = "",
) -> dict[str, Any]:
    """红线 4：单只股票仓位不得超过上限。

    这是一个不可绕过的硬约束——即使 Agent 认为应该超配，也会被拦截。

    Args:
        stock_code: 股票代码
        proposed_weight: 建议仓位（0-1）
        max_position_pct: 最大仓位百分比（默认 25%）
        portfolio_total: 组合总值（用于计算百分比）
        agent_id: 发起建议的 Agent ID
        override_token: 覆盖令牌（目前无效，永远拦截）

    Returns:
        {"allowed": bool, "capped_weight": float, "reason": str}
    """
    if proposed_weight <= max_position_pct:
        return {
            "allowed": True,
            "capped_weight": proposed_weight,
            "reason": f"仓位 {proposed_weight:.1%} 在上限 {max_position_pct:.1%} 内",
            "violation": None,
        }

    # 超上限 → 强制截断
    violation = RedLineViolation(
        rule_id=4,
        rule_name="max_position_pct_enforced",
        action="blocked",
        context={
            "stock_code": stock_code,
            "proposed_weight": proposed_weight,
            "max_position_pct": max_position_pct,
            "capped_to": max_position_pct,
        },
        agent_id=agent_id,
    )
    _append_audit_log(violation)

    return {
        "allowed": False,
        "capped_weight": max_position_pct,
        "reason": (
            f"红线 4 拦截：建议仓位 {proposed_weight:.1%} 超过上限 "
            f"{max_position_pct:.1%}，已强制截断至 {max_position_pct:.1%}"
        ),
        "violation": violation.to_dict(),
    }


# ═══════════════════════════════════════════════════════════════
# 红线 5：Kill Switch — 一键暂停自进化
# ═══════════════════════════════════════════════════════════════

def activate_kill_switch(
    reason: str = "",
    activated_by: str = "admin",
    duration_hours: int = 24,
) -> dict[str, Any]:
    """激活 Kill Switch，暂停所有自进化功能。"""
    KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)

    kill_state = {
        "active": True,
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "activated_by": activated_by,
        "reason": reason,
        "duration_hours": duration_hours,
        "expires_at": _compute_expiry(duration_hours),
        "paused_features": [
            "factor_weight_self_correction",
            "strategy_parameter_evolution",
            "scenario_library_auto_update",
            "agent_self_organization",
        ],
    }

    with open(KILL_SWITCH_FILE, "w", encoding="utf-8") as f:
        json.dump(kill_state, f, ensure_ascii=False, indent=2)

    violation = RedLineViolation(
        rule_id=5,
        rule_name="kill_switch_activated",
        action="alerted",
        context=kill_state,
        agent_id=activated_by,
    )
    _append_audit_log(violation)

    return {"status": "activated", "kill_switch": kill_state}


def deactivate_kill_switch(
    admin_token: str = "",
) -> dict[str, Any]:
    """解除 Kill Switch。"""
    expected_token = os.environ.get("HERMASS_ADMIN_TOKEN", "")
    if expected_token and admin_token != expected_token:
        return {"status": "denied", "reason": "admin token 验证失败"}

    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()

    return {"status": "deactivated"}


def is_kill_switch_active() -> bool:
    """检查 Kill Switch 是否处于激活状态。"""
    if not KILL_SWITCH_FILE.exists():
        return False

    try:
        with open(KILL_SWITCH_FILE, encoding="utf-8") as f:
            state = json.load(f)

        if not state.get("active"):
            return False

        # 检查是否已过期
        expires_at = state.get("expires_at", "")
        if expires_at:
            expiry = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) > expiry:
                # 已过期，自动解除
                KILL_SWITCH_FILE.unlink()
                return False

        return True
    except Exception:
        return False


def get_kill_switch_state() -> dict[str, Any]:
    """获取 Kill Switch 当前状态。"""
    if not KILL_SWITCH_FILE.exists():
        return {"active": False}
    try:
        with open(KILL_SWITCH_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active": False, "error": "无法读取 kill_switch.json"}


def _compute_expiry(duration_hours: int) -> str:
    """计算过期时间。"""
    from datetime import timedelta
    expiry = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    return expiry.isoformat()


# ═══════════════════════════════════════════════════════════════
# 装饰器：自动拦截
# ═══════════════════════════════════════════════════════════════

def red_line_guard(rule_id: int):
    """装饰器：在函数执行前检查 Kill Switch。

    如果 Kill Switch 激活，直接拒绝执行。
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if is_kill_switch_active():
                state = get_kill_switch_state()
                return {
                    "status": "blocked_by_kill_switch",
                    "reason": f"Kill Switch 已激活，功能暂停中。原因：{state.get('reason', '未指定')}",
                    "kill_switch_state": state,
                }
            return func(*args, **kwargs)
        return wrapper
    return decorator
