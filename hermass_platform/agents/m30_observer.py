#!/usr/bin/env python3
"""M30Observer Agent — 30分钟盘中精细观察器。

定位：M30 只做盘中收缩→突破事件的精细检测，不单独拍板交易决策。
输出作为 Agent Debate 的观察证据输入，供 Dynamic Weight Router 做权重分配。

检测维度：
  1. M30 收缩状态：BB20 width squeeze + ADX 低位
  2. M30 突破确认：价格突破日内前高 + ADX 斜率转正 + 收盘在 MA20 上方
  3. M30 与 D1/W1 周期共振：大周期收缩时 M30 提供精确入场/离场时点
  4. M30 风险信号：ADX 斜率转负 + 价格回落到 MA20 下方

硬规则（来自 AGENTS.MD）：
  - M30 Agent 只做盘中观察和精确位置判断，不单独拍板
  - Risk Agent 必须作为常驻反驳者
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

try:
    from .base_agent import AgentContext, AgentResult, find_foundation_db
except ImportError:
    from base_agent import AgentContext, AgentResult, find_foundation_db

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("m30_observer")

AGENT_ID = "m30_observer"
AGENT_NAME = "M30精细观察器"

# M30 观察评分阈值
M30_THRESHOLDS = {
    "adx_slope_min": 0.0,           # ADX 斜率至少为正
    "adx_low_max": 25.0,            # ADX < 25 视为低位（收缩期）
    "bb_width_squeeze_pct": 0.05,   # BB width < 5% 视为 squeeze
}


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"DESCRIBE {table}").fetchdf()
        return column in rows["column_name"].values
    except Exception:
        return False


def observe_m30_intraday(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    stock_codes: Optional[list[str]] = None,
    session_id: str = "",
) -> dict:
    """M30 盘中精细观察入口。

    Returns:
        AgentResult.to_dict() 格式，包含：
        - m30_observations: 每只股票的 M30 观察结果列表
        - m30_breakout_candidates: 突破候选（ADX 斜率 > 0 + 价格突破）
        - m30_contraction_pool: 收缩池（BB squeeze + ADX 低位）
        - m30_risk_flags: 风险标记（ADX 转负 + 价格回落）
    """
    ctx = AgentContext(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    if not foundation_db:
        db_path = find_foundation_db(target_date)
        if db_path is None:
            return AgentResult(
                agent_id=AGENT_ID,
                agent_name=AGENT_NAME,
                status="error",
                errors=["无可用 Foundation DB"],
            ).to_dict()
        foundation_db = str(db_path)

    result = AgentResult(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        status="ok",
    )

    try:
        con = duckdb.connect(foundation_db, read_only=True)

        # 确定实际日期
        if target_date:
            actual_date = target_date
        else:
            latest = con.execute("SELECT MAX(state_date) FROM d1_perspective_state").fetchone()
            actual_date = str(latest[0]) if latest and latest[0] else ""

        if not actual_date:
            result.status = "error"
            result.errors.append("无法确定目标日期")
            return result.to_dict()

        # 检查 M30 字段是否存在
        has_m30 = _column_exists(con, "d1_perspective_state", "m30_adx_slope_3")
        if not has_m30:
            result.status = "warning"
            result.summary = "Foundation DB 无 M30 字段，M30 观察跳过"
            result.data = {
                "m30_observations": [],
                "m30_breakout_candidates": [],
                "m30_contraction_pool": [],
                "m30_risk_flags": [],
                "has_m30_data": False,
                "actual_date": actual_date,
            }
            return result.to_dict()

        # 构建股票过滤条件
        code_filter = ""
        if stock_codes and len(stock_codes) > 0:
            code_str = "('" + "', '".join(stock_codes) + "')"
            code_filter = f"AND stock_code IN {code_str}"

        # ── 核心查询：M30 观察数据 ──
        sql = f"""
            SELECT
                stock_code,
                d1_state_hex,
                w1_state_hex,
                mn1_state_hex,
                d1_close,
                m30_close,
                m30_adx14,
                m30_adx_slope_3,
                m30_breakout_signal,
                m30_price_breakout,
                m30_ma20_ready,
                m30_close_vs_ma20_flag,
                m30_intraday_prev_high,
                ef_count,
                d1_adx14,
                d1_bb_width_pct,
                d1_volatility
            FROM d1_perspective_state
            WHERE state_date = DATE '{actual_date}'
              {code_filter}
            ORDER BY ef_count, stock_code
            LIMIT 500
        """
        df = con.execute(sql).fetchdf()
        con.close()

        if df.empty:
            result.status = "warning"
            result.summary = f"{actual_date} 无数据"
            result.data = {
                "m30_observations": [],
                "has_m30_data": True,
                "actual_date": actual_date,
            }
            return result.to_dict()

        # ── M30 观察评分 ──
        observations = []
        breakout_candidates = []
        contraction_pool = []
        risk_flags = []

        for _, row in df.iterrows():
            stock_code = row["stock_code"]
            d1_hex = row["d1_state_hex"] or ""
            w1_hex = row["w1_state_hex"] or ""
            ef_count = row["ef_count"] or 0

            m30_adx = row["m30_adx14"] or 0
            m30_adx_slope = row["m30_adx_slope_3"] or -999
            m30_breakout_sig = row["m30_breakout_signal"] if pd.notna(row["m30_breakout_signal"]) else 0
            m30_price_break = row["m30_price_breakout"] if pd.notna(row["m30_price_breakout"]) else 0
            m30_ma20_ready = row["m30_ma20_ready"] if pd.notna(row["m30_ma20_ready"]) else False
            m30_close_vs_ma20 = row["m30_close_vs_ma20_flag"] if pd.notna(row["m30_close_vs_ma20_flag"]) else 0
            m30_close = row["m30_close"] if pd.notna(row["m30_close"]) else 0
            m30_prev_high = row["m30_intraday_prev_high"] if pd.notna(row["m30_intraday_prev_high"]) else 0

            d1_adx = row["d1_adx14"] or 0
            d1_bb_width = row["d1_bb_width_pct"] or 0

            obs = {
                "stock_code": stock_code,
                "d1_state_hex": d1_hex,
                "w1_state_hex": w1_hex,
                "ef_count": ef_count,
                "m30_adx14": m30_adx,
                "m30_adx_slope_3": m30_adx_slope,
                "m30_breakout_signal": m30_breakout_sig,
                "m30_price_breakout": m30_price_break,
                "m30_ma20_ready": bool(m30_ma20_ready),
                "m30_close_vs_ma20_flag": m30_close_vs_ma20,
                "m30_close": m30_close,
                "m30_intraday_prev_high": m30_prev_high,
                "d1_adx14": d1_adx,
                "d1_bb_width_pct": d1_bb_width,
                # 观察标签
                "m30_contraction": False,
                "m30_breakout_confirmed": False,
                "m30_risk_flag": False,
                "m30_resonance": False,
                "score": 0,
            }

            # 1. M30 收缩检测：ADX 低位 + D1 BB width 小
            is_m30_contraction = (
                m30_adx < M30_THRESHOLDS["adx_low_max"]
                and d1_bb_width > 0
                and d1_bb_width < M30_THRESHOLDS["bb_width_squeeze_pct"]
            )
            obs["m30_contraction"] = bool(is_m30_contraction)

            # 2. M30 突破确认（最严格的条件）
            is_breakout = False
            if m30_ma20_ready:
                is_breakout = (
                    m30_adx_slope > M30_THRESHOLDS["adx_slope_min"]
                    and m30_close_vs_ma20 >= 1
                    and m30_price_break == 1
                )
            obs["m30_breakout_confirmed"] = bool(is_breakout)

            # 3. M30 风险标记
            is_risk = False
            if m30_ma20_ready:
                is_risk = (
                    m30_adx_slope < 0
                    and m30_close_vs_ma20 < 1
                )
            obs["m30_risk_flag"] = bool(is_risk)

            # 4. 多周期共振：D1/W1 都是 E/F + M30 突破
            is_resonance = (
                ef_count >= 2
                and is_breakout
            )
            obs["m30_resonance"] = bool(is_resonance)

            # 5. 综合评分（0-100）
            score = 0
            if is_breakout:
                score += 40
            if is_resonance:
                score += 30
            if m30_adx_slope > 0:
                score += 10
            if m30_price_break == 1:
                score += 10
            if m30_ma20_ready:
                score += 10
            obs["score"] = min(score, 100)

            observations.append(obs)

            if is_breakout:
                breakout_candidates.append(obs)
            if is_m30_contraction:
                contraction_pool.append(obs)
            if is_risk:
                risk_flags.append(obs)

        # 排序
        breakout_candidates.sort(key=lambda x: x["score"], reverse=True)
        contraction_pool.sort(key=lambda x: x["ef_count"], reverse=True)

        result.summary = (
            f"M30 观察完成: {len(observations)} 只, "
            f"突破候选 {len(breakout_candidates)}, "
            f"收缩池 {len(contraction_pool)}, "
            f"风险标记 {len(risk_flags)}"
        )
        result.data = {
            "m30_observations": observations,
            "m30_breakout_candidates": breakout_candidates,
            "m30_contraction_pool": contraction_pool,
            "m30_risk_flags": risk_flags,
            "has_m30_data": True,
            "actual_date": actual_date,
            "total_observed": len(observations),
            "breakout_count": len(breakout_candidates),
            "contraction_count": len(contraction_pool),
            "risk_count": len(risk_flags),
        }

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))
        log.exception("M30 观察失败")

    return result.to_dict()


def main():
    """CLI 入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="M30 盘中精细观察")
    parser.add_argument("--date", default="", help="目标日期 YYYY-MM-DD")
    parser.add_argument("--foundation", default="", help="Foundation DB 路径")
    parser.add_argument("--user-id", default="system", help="用户 ID")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    result = observe_m30_intraday(
        user_id=args.user_id,
        target_date=args.date,
        foundation_db=args.foundation,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n已写入: {args.output}")


if __name__ == "__main__":
    main()
