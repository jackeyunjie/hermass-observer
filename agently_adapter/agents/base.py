"""Agent 基础工具 —— 所有 LLM Agent 共享的初始化、调用和全局规则。"""

from __future__ import annotations

import os
from typing import Any

try:
    from agently import Agently
except ImportError:  # pragma: no cover
    Agently = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# 全局规则（所有 Agent 共享）
# ---------------------------------------------------------------------------

GLOBAL_SYSTEM_HEADER = (
    "你是 Hermass 多周期观测台的 AI 助手集群中的一员。"
    "Hermass 是一个基于 A 股多周期 State 模型的交易辅助系统。\n\n"
    "## 全局约束\n"
    "1. 你只能分析 A 股（含 ETF），不分析期货、外盘、加密货币。\n"
    "2. 所有数值必须标注来源（同花顺/黑狼资金流/AI估算/手动维护）。\n"
    "3. 禁止给出具体买入价位、目标价位、持仓比例。\n"
    "4. 每句话必须有数据或逻辑支撑，禁止纯定性断言。\n"
    "5. 回答中必须包含风险提示：「本分析仅供参考，不构成投资建议。」\n\n"
    "## State 编码体系（计算层）\n"
    "- State 由 4 bit 组成：bit3=趋势(0/1) bit2=突破(0/1) bit1=波动(0/1) bit0=方向(0跌/1涨)\n"
    "- 正值 = 上涨方向，负值 = 下跌方向（符号单独编码）\n"
    "- E(14)=强趋势+突破+扩张+涨, F(15)=同上+方向确认\n"
    "- ef_count = MN1/W1/D1 中 E/F/C/D 的个数，代表共振强度\n\n"
    "## 表达层映射（用户看到的）\n"
    "- E/F → 天时（🔥）  C/D → 地利（☀️）  8/9/A/B → 人和（🌤）\n"
    "- 4/5/6/7 → 蓄力（🌥）  0/1/2/3 → 冬眠（🌧）  负值 → 逆位（⚡）\n"
    "- ef=3 天时共振 | ef=2 地利共振 | ef=1 单一周期 | ef=0 无共振/逆位\n\n"
    "## 禁用词库（绝对禁止）\n"
    "谨慎乐观、结构追踪、密切关注、适当参与、中长期看好、有望、或将、"
    "值得重视、具备潜力、建议关注、保持跟踪、中性偏多、震荡偏强、"
    "下行空间有限、估值合理、安全边际\n\n"
    "## 可用替代词\n"
    "- 谨慎乐观 → 观望/等待信号\n"
    "- 结构追踪 → 跟踪确认/观察队列\n"
    "- 密切关注 → 列入观察/设置提醒\n"
    "- 适当参与 → 轻仓跟踪/标准跟踪\n"
    "- 有望上涨 → 顺风环境/趋势确认"
)


# ---------------------------------------------------------------------------
# Agently 运行时初始化
# ---------------------------------------------------------------------------

_SETTINGS_READY = False


def _ensure_settings() -> bool:
    """确保 Agently DeepSeek 配置已初始化（幂等）。"""
    global _SETTINGS_READY
    if _SETTINGS_READY:
        return True
    if Agently is None:
        return False

    api_key = (
        os.environ.get("HERMASS_DEEPSEEK_API_KEY", "").strip()
        or os.environ.get("DEEPSEEK_API_KEY", "").strip()
    )
    if not api_key:
        return False
    model = (
        os.environ.get("HERMASS_DEEPSEEK_MODEL", "").strip()
        or os.environ.get("HERMASS_LLM_MODEL", "deepseek-chat").strip()
    )
    base_url = (
        os.environ.get("HERMASS_DEEPSEEK_BASE_URL", "").strip()
        or os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()
    )
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    try:
        Agently.set_settings(
            "OpenAICompatible",
            {"base_url": base_url, "api_key": api_key, "model": model},
        )
        _SETTINGS_READY = True
        return True
    except Exception:
        return False


def create_agent() -> Any:
    """创建并配置好 Agently Agent（已注入全局系统提示）。"""
    if not _ensure_settings():
        raise RuntimeError("Agently settings not available")
    agent = Agently.create_agent()
    agent.system(GLOBAL_SYSTEM_HEADER)
    return agent


def safe_get_response(agent: Any, timeout: float = 60.0) -> dict[str, Any] | None:
    """安全地获取 Agent 响应，任何异常都返回 None（调用方应回退）。"""
    try:
        response = agent.get_response(timeout=timeout)
        result = response.result.get_data() if response.result else {}
        return result if isinstance(result, dict) else None
    except Exception:
        return None
