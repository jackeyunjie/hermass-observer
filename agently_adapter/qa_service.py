"""Hermass 统一问答服务层（Q&A Service Layer）

通过 Agently 框架统一管理大模型调用，为 web AI 助手提供：
- 结构化输出（answer, why, multi_cycle_view, ...）
- 运行时观测（observation events, action logs）
- 模型配置统一收口（DeepSeek）

约束：
- Web 层不直接调用 Agently runtime，只调用此服务层。
- 所有模型配置在此文件中收口，web/main.py 不感知 provider 细节。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════
# Agently import（web 层不直接 import，由本层统一封装）
# ═══════════════════════════════════════════════════════════════════
try:
    from agently import Agently
except ImportError:  # pragma: no cover
    Agently = None  # type: ignore[misc, assignment]

_ROOT = Path(__file__).resolve().parents[1]
_OBS_DB = _ROOT / "outputs" / "agently_observation_logs.db"

# ═══════════════════════════════════════════════════════════════════
# 1. 初始化与配置
# ═══════════════════════════════════════════════════════════════════


def _init_settings() -> bool:
    """初始化 Agently DeepSeek 配置。

    环境变量优先级（从高到低）：
      HERMASS_DEEPSEEK_API_KEY > DEEPSEEK_API_KEY
      HERMASS_DEEPSEEK_MODEL    > HERMASS_LLM_MODEL > deepseek-chat
      HERMASS_DEEPSEEK_BASE_URL > DEEPSEEK_API_BASE > https://api.deepseek.com/v1

    返回 True 表示配置成功，False 表示缺少必要配置（如 api_key）。
    """
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
    if model == "deepseekV4":
        model = "deepseek-chat"

    base_url = (
        os.environ.get("HERMASS_DEEPSEEK_BASE_URL", "").strip()
        or os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").strip()
    )
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"

    try:
        Agently.set_settings(
            "OpenAICompatible",
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
            },
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# 2. Prompt 资产（统一收口，不散落在 web 层）
# ═══════════════════════════════════════════════════════════════════


def _base_system_prompt() -> str:
    return (
        "你是 Hermass 多周期观测台的 AI 助手。你只做解释、翻译和导航，不做投资建议。"
        "你必须坚持多周期环境、单周期位置、风险控制这条主线。"
        "输出必须是 JSON，且字段必须包含 answer, why, multi_cycle_view, single_cycle_position, "
        "avoid, next_actions, sources, freshness_note。"
    )


def _base_output_schema() -> dict[str, Any]:
    """Agently 4.1 结构化输出 schema。

    格式: {字段名: (类型, 描述, 是否必填)}
    必填字段第三个参数为 True。
    """
    return {
        "answer": (str, "核心结论，30字以内，yes/no风格", True),
        "why": (str, "2-3个理由，用数据说话", True),
        "multi_cycle_view": (str, "多周期视角判断", True),
        "single_cycle_position": (str, "单周期位置判断", True),
        "avoid": (str, "风险提示", True),
        "next_actions": ([{"label": str, "url": str}], "建议动作列表", True),
        "sources": ([str], "数据来源列表", True),
        "freshness_note": (str, "数据时效说明", True),
    }


# ═══════════════════════════════════════════════════════════════════
# 3. 统一问答入口
# ═══════════════════════════════════════════════════════════════════


def _run_agent(
    system_prompt: str,
    instruct: str,
    payload: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """运行 Agently agent，返回结构化 JSON。

    失败时返回 None，调用方应回退到规则回答。
    """
    if Agently is None:
        return None
    if not _init_settings():
        return None

    try:
        agent = Agently.create_agent()
        agent.system(system_prompt)
        agent.instruct(instruct)
        agent.input(
            "请根据以下结构化输入回答，并严格输出 JSON，不要输出 Markdown。\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        schema = output_schema or _base_output_schema()
        agent.output(schema)

        response = agent.get_response()
        result = response.result.get_data() if response.result else {}

        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return None


def answer_market(market_data: dict[str, Any]) -> dict[str, Any] | None:
    """市场类问题：由 Agently 基于 market_data 生成回答。

    入参 market_data 即 _market_analysis_data() 的完整返回。
    返回值与 ChatResponse 的 JSON 字段对齐。
    """
    result = _run_agent(
        system_prompt=_base_system_prompt(),
        instruct="请根据以下市场数据回答用户关于市场环境的问题。",
        payload={"market_data": market_data},
    )
    if result:
        _log_observation("market", result)
    return result


def answer_industry(industry_data: dict[str, Any]) -> dict[str, Any] | None:
    """行业类问题。"""
    result = _run_agent(
        system_prompt=_base_system_prompt(),
        instruct="请根据以下行业轮动数据回答用户关于行业方向的问题。",
        payload={"industry_rotation": industry_data},
    )
    if result:
        _log_observation("industry", result)
    return result


def answer_value_research(stock_code: str, research_context: dict[str, Any]) -> dict[str, Any] | None:
    """价值分析类问题。"""
    result = _run_agent(
        system_prompt=_base_system_prompt(),
        instruct="请根据以下价值研究数据回答用户关于个股价值分析的问题。",
        payload={"stock_code": stock_code, "research_context": research_context},
    )
    if result:
        _log_observation("value_research", result)
    return result


def answer_stock(stock_code: str, stock_context: dict[str, Any]) -> dict[str, Any] | None:
    """个股类问题。"""
    result = _run_agent(
        system_prompt=_base_system_prompt(),
        instruct="请根据以下个股数据回答用户关于个股结构和策略适配的问题。",
        payload={"stock_code": stock_code, "stock_context": stock_context},
    )
    if result:
        _log_observation("stock", result)
    return result


# ═══════════════════════════════════════════════════════════════════
# 4. 运行时观测（Observation）
# ═══════════════════════════════════════════════════════════════════


def _ensure_obs_table() -> sqlite3.Connection:
    _OBS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_OBS_DB), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agently_observation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            result_json TEXT NOT NULL,
            latency_ms INTEGER,
            error TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    con.commit()
    return con


def _log_observation(category: str, result: dict[str, Any], latency_ms: int = 0, error: str = "") -> None:
    """记录 Agently 运行观测日志到 SQLite。"""
    con = _ensure_obs_table()
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO agently_observation_logs (category, result_json, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?)",
        (category, json.dumps(result, ensure_ascii=False), latency_ms, error, now),
    )
    con.commit()
    con.close()


def get_recent_observation_logs(category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """获取最近观测日志。

    Args:
        category: 过滤类别（market/industry/value_research/stock），None 表示全部。
        limit: 返回条数上限。
    """
    con = _ensure_obs_table()
    if category:
        rows = con.execute(
            "SELECT * FROM agently_observation_logs WHERE category = ? ORDER BY created_at DESC LIMIT ?",
            (category, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM agently_observation_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_observation_summary() -> dict[str, Any]:
    """获取观测统计摘要。"""
    con = _ensure_obs_table()
    total = con.execute("SELECT COUNT(*) FROM agently_observation_logs").fetchone()[0]
    errors = con.execute("SELECT COUNT(*) FROM agently_observation_logs WHERE error != ''").fetchone()[0]
    cats = con.execute(
        "SELECT category, COUNT(*) as cnt FROM agently_observation_logs GROUP BY category"
    ).fetchall()
    latest = con.execute(
        "SELECT created_at FROM agently_observation_logs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    con.close()
    return {
        "total_calls": total,
        "error_calls": errors,
        "success_rate": round((total - errors) / total * 100, 1) if total else 0.0,
        "category_distribution": {r["category"]: r["cnt"] for r in cats},
        "latest_call_at": latest["created_at"] if latest else None,
    }
