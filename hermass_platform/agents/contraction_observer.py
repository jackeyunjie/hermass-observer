#!/usr/bin/env python3
"""ContractionObserver Agent — 收缩突破观测器。

基于 AgentContext 基类，每日收盘后扫描全市场：
  1. 三重交叉验证：BB < Q20、枢轴 < Q20、ATR < Q20（三选二触发收缩）
  2. 六重突破确认：V1-V4 硬件 + V5/V6 加权加分
  3. 极致收缩检测：squeeze_score > 80 且 BB < Q5
  4. 20 日 Supersede 去重
  5. 结果写入 AgentMemory (agent_judgments)
  6. 异常事件通过 AgentBus 广播

用法：
  from hermass_platform.agents.contraction_observer import observe_contraction
  result = observe_contraction(user_id="u001")
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from .base_agent import AgentContext, AgentResult, find_foundation_db

ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger("contraction_observer")

# ── 常量 ──────────────────────────────────────────────────────
AGENT_ID = "contraction_observer"
AGENT_NAME = "收缩突破观测器"
SUPERSEDE_DAYS = 20  # 同标的突破后 20 日内不重复触发

# 六重突破确认的权重
BREAKOUT_WEIGHTS = {
    "V1_price_break_sr": 0.25,    # 价格突破 SR
    "V2_volume_a_grade": 0.25,    # 量能 A 级
    "V3_bb_width_jump": 0.20,     # BB 带宽跳升
    "V4_adx_recovery": 0.20,      # ADX 回升
    "V5_industry_resonance": 0.10,  # 行业共振（加分）
    "V6_capital_flow": 0.10,      # 资金流确认（加分）
}

# AgentMemory 路径
DEFAULT_AGENT_MEMORY = ROOT / "outputs" / "agent_memory" / "AgentMemory.duckdb"


# ── 辅助 ─────────────────────────────────────────────────────

def _column_exists(conn, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"DESCRIBE {table}").fetchdf()
        return column in rows["column_name"].values
    except Exception:
        return False


def _table_exists(conn, table: str) -> bool:
    tables = conn.execute("SHOW TABLES").fetchdf()
    return table in tables["name"].values


# ── Step 1: 三重交叉验证 ──────────────────────────────────────

def detect_contraction(
    conn: duckdb.DuckDBPyConnection,
    target_date: str,
) -> pd.DataFrame:
    """检测处于收缩状态的股票。

    三重交叉验证：BB < Q20、枢轴 < Q20、ATR < Q20（三选二即触发）。
    """
    if not _table_exists(conn, "bb_pivot_atr"):
        log.warning("bb_pivot_atr 表不存在，无法执行收缩检测")
        return pd.DataFrame()

    sql = f"""
        SELECT
            stock_code,
            state_date,
            timeframe,
            bb_width_pct,
            bb_width_q10,
            bb_width_q20,
            pivot_width,
            pivot_width_q20,
            atr_ratio_pct,
            atr_ratio_q20,
            triple_squeeze,
            squeeze_score,
            data_quality_score
        FROM bb_pivot_atr
        WHERE state_date = DATE '{target_date}'
          AND data_quality_score = 0
    """
    df = conn.execute(sql).fetchdf()

    if df.empty:
        log.warning("无 bb_pivot_atr 数据 (date=%s)", target_date)
        return df

    # 三选二判断
    df["bb_below_q20"] = df["bb_width_pct"] < df["bb_width_q20"]
    df["pivot_below_q20"] = df["pivot_width"] < df["pivot_width_q20"]
    df["atr_below_q20"] = df["atr_ratio_pct"] < df["atr_ratio_q20"]

    df["contraction_count"] = (
        df["bb_below_q20"].astype(int) +
        df["pivot_below_q20"].astype(int) +
        df["atr_below_q20"].astype(int)
    )

    # 三选二触发
    df["is_contraction"] = df["contraction_count"] >= 2

    # 极致收缩: squeeze_score > 80 且 BB < Q5
    # 需要 bb_width_q5 — 从 stock_percentile_thresholds 获取
    if _table_exists(conn, "stock_percentile_thresholds"):
        q5_sql = f"""
            SELECT stock_code, timeframe, q5 AS bb_q5
            FROM stock_percentile_thresholds
            WHERE metric_name = 'bb_width'
              AND lookback_bars = 60
              AND last_updated = DATE '{target_date}'
        """
        q5_df = conn.execute(q5_sql).fetchdf()
        if not q5_df.empty:
            df = df.merge(q5_df, on=["stock_code", "timeframe"], how="left")
            df["is_extreme"] = (
                (df["squeeze_score"].fillna(0) > 80) &
                (df["bb_width_pct"] < df["bb_q5"])
            )
        else:
            df["bb_q5"] = np.nan
            df["is_extreme"] = (df["squeeze_score"].fillna(0) > 80)
    else:
        df["bb_q5"] = np.nan
        df["is_extreme"] = (df["squeeze_score"].fillna(0) > 80)

    contraction_df = df[df["is_contraction"]].copy()
    log.info(
        "收缩检测: %d/%d 只股票触发 (%d 极致收缩)",
        len(contraction_df),
        len(df),
        contraction_df["is_extreme"].sum() if "is_extreme" in contraction_df.columns else 0,
    )

    return contraction_df


# ── Step 2: 六重突破确认 ──────────────────────────────────────

def evaluate_breakout(
    conn: duckdb.DuckDBPyConnection,
    stock_code: str,
    target_date: str,
    timeframe: str = "D1",
) -> dict:
    """对收缩中的股票评估突破确认程度。

    V1: 价格突破 SR 阻力位
    V2: 成交量 A 级（> 20 日均量 × 1.5）
    V3: BB 带宽跳升（当前 BB > 前日 BB × 1.2）
    V4: ADX 回升（ADX > 25 且上升中）
    V5: 行业共振（同行业 ≥ 3 只股票同时收缩）
    V6: 资金流确认（主力资金净流入）

    Returns:
        dict: 包含各维度评分和综合判断
    """
    result = {
        "stock_code": stock_code,
        "timeframe": timeframe,
        "checks": {},
        "confirmed_count": 0,
        "confidence": 0.0,
        "label": "未突破",
    }

    # V1: 价格突破 SR
    tf_sr_map = {
        "D1": ("d1_sr_resistance",),
        "W1": ("w1_sr_resistance",),
        "MN1": ("mn1_sr_resistance",),
    }
    res_col = tf_sr_map.get(timeframe, ("d1_sr_resistance",))[0]
    v1_sql = f"""
        SELECT d1_close, {res_col} AS sr_resistance
        FROM d1_perspective_state
        WHERE stock_code = '{stock_code}'
          AND state_date = DATE '{target_date}'
    """
    v1_df = conn.execute(v1_sql).fetchdf()
    if not v1_df.empty:
        row = v1_df.iloc[0]
        close = row.get("d1_close", 0) or 0
        sr_res = row.get("sr_resistance")
        if sr_res and close > sr_res:
            result["checks"]["V1_price_break_sr"] = True
        else:
            result["checks"]["V1_price_break_sr"] = False
    else:
        result["checks"]["V1_price_break_sr"] = False

    # V2: 量能 A 级（当日成交量 > 20 日均量 × 1.5）
    v2_sql = f"""
        SELECT volume
        FROM timeframe_indicators
        WHERE stock_code = '{stock_code}'
          AND timeframe = '{timeframe}'
          AND available_date <= DATE '{target_date}'
        ORDER BY available_date DESC
        LIMIT 20
    """
    v2_df = conn.execute(v2_sql).fetchdf()
    if len(v2_df) >= 5 and "volume" in v2_df.columns:
        vol_today = v2_df.iloc[0].get("volume", 0) or 0
        vol_avg20 = v2_df["volume"].mean()
        if vol_avg20 > 0:
            vol_ratio = vol_today / vol_avg20
            result["checks"]["V2_volume_a_grade"] = vol_ratio >= 1.5
        else:
            result["checks"]["V2_volume_a_grade"] = False
    else:
        result["checks"]["V2_volume_a_grade"] = False

    # V3: BB 带宽跳升（当前 BB > 前日 BB × 1.2）
    v3_sql = f"""
        SELECT bb_width_pct, prev_bb_width_pct
        FROM timeframe_indicators
        WHERE stock_code = '{stock_code}'
          AND timeframe = '{timeframe}'
          AND available_date = DATE '{target_date}'
    """
    v3_df = conn.execute(v3_sql).fetchdf()
    if not v3_df.empty:
        bb_today = v3_df.iloc[0].get("bb_width_pct", 0) or 0
        bb_prev = v3_df.iloc[0].get("prev_bb_width_pct", 0) or 0
        if bb_prev > 0:
            result["checks"]["V3_bb_width_jump"] = bb_today > bb_prev * 1.2
        else:
            result["checks"]["V3_bb_width_jump"] = bb_today > 0
    else:
        result["checks"]["V3_bb_width_jump"] = False

    # V4: ADX 回升（adx14 > 25 且 > prev_adx14）
    v4_sql = f"""
        SELECT adx14, prev_adx14
        FROM timeframe_indicators
        WHERE stock_code = '{stock_code}'
          AND timeframe = '{timeframe}'
          AND available_date = DATE '{target_date}'
    """
    v4_df = conn.execute(v4_sql).fetchdf()
    if not v4_df.empty and "adx14" in v4_df.columns:
        adx_today = v4_df.iloc[0].get("adx14", 0) or 0
        adx_prev = v4_df.iloc[0].get("prev_adx14", 0) or 0
        result["checks"]["V4_adx_recovery"] = (adx_today > 25) and (adx_today > adx_prev)
    else:
        result["checks"]["V4_adx_recovery"] = False

    # V5: 行业共振（简化：检查同日收缩股票数量 ≥ 100）
    v5_sql = f"""
        SELECT COUNT(*) FROM bb_pivot_atr
        WHERE state_date = DATE '{target_date}'
          AND triple_squeeze = TRUE
    """
    squeeze_count = conn.execute(v5_sql).fetchone()[0]
    result["checks"]["V5_industry_resonance"] = squeeze_count >= 100

    # V6: 资金流确认（简化：检查 moneyflow 表中是否有净流入）
    result["checks"]["V6_capital_flow"] = False
    if _table_exists(conn, "moneyflow_daily"):
        v6_sql = f"""
            SELECT net_inflow
            FROM moneyflow_daily
            WHERE stock_code = '{stock_code}'
              AND trade_date = DATE '{target_date}'
        """
        v6_df = conn.execute(v6_sql).fetchdf()
        if not v6_df.empty:
            net_in = v6_df.iloc[0].get("net_inflow", 0) or 0
            result["checks"]["V6_capital_flow"] = net_in > 0

    # ── 归一化布尔值（numpy bool_ → Python bool） ──
    result["checks"] = {k: bool(v) for k, v in result["checks"].items()}

    # ── 综合评分 ──
    confirmed = sum(1 for v in result["checks"].values if v)
    result["confirmed_count"] = confirmed

    # 计算加权置信度
    weighted_score = sum(
        BREAKOUT_WEIGHTS[k] for k, v in result["checks"].items() if v
    )
    result["confidence"] = round(weighted_score, 2)

    # 判断标签
    v1 = result["checks"].get("V1_price_break_sr", False)
    v2 = result["checks"].get("V2_volume_a_grade", False)
    v3 = result["checks"].get("V3_bb_width_jump", False)
    v4 = result["checks"].get("V4_adx_recovery", False)

    if v1 and v2 and v3 and v4:
        result["label"] = "确认突破"
        result["confidence"] = max(result["confidence"], 0.85)
    elif v1 and v2:
        result["label"] = "疑似突破"
        result["confidence"] = max(result["confidence"], 0.50)
    elif v1:
        result["label"] = "观察"
        # V1 单触发不产生信号
    else:
        result["label"] = "未突破"

    return result


# ── Step 3: Supersede 去重 ────────────────────────────────────

def check_supersede(
    memory_conn: duckdb.DuckDBPyConnection,
    stock_code: str,
    target_date: str,
) -> bool:
    """检查同标的是否在 20 日内已有突破记录。

    使用 json_extract_string 从 judgment_content 中结构化提取 stock_code，
    而非 LIKE 字符串匹配。

    Returns:
        True 表示应跳过（已被 supersede）
    """
    if not _table_exists(memory_conn, "agent_judgments"):
        return False

    cutoff = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=SUPERSEDE_DAYS)).strftime("%Y-%m-%d")

    sql = f"""
        SELECT COUNT(*)
        FROM agent_judgments
        WHERE agent_id = '{AGENT_ID}'
          AND judgment_type = 'breakout_confirmed'
          AND judgment_date >= DATE '{cutoff}'
          AND judgment_date < DATE '{target_date}'
          AND json_extract_string(judgment_content, '$.stock_code') = '{stock_code}'
    """
    try:
        count = memory_conn.execute(sql).fetchone()[0]
        return count > 0
    except Exception as e:
        log.warning("Supersede 查询异常: %s", e)
        return False


# ── Step 4: 写入 AgentMemory ──────────────────────────────────

def write_judgment(
    memory_conn: duckdb.DuckDBPyConnection,
    target_date: str,
    judgments: list[dict],
) -> int:
    """将判断结果写入 agent_judgments 表。

    按 (stock_code, judgment_date) 去重：先删除同日同标的旧记录再插入。
    """
    if not judgments:
        return 0

    rows = []
    stock_codes = set()
    for j in judgments:
        stock_code = j.get("content", {}).get("stock_code", "")
        if stock_code:
            stock_codes.add(stock_code)
        rows.append({
            "agent_id": AGENT_ID,
            "judgment_id": str(uuid.uuid4()),
            "judgment_date": target_date,
            "judgment_type": j["type"],
            "judgment_content": json.dumps(j["content"], ensure_ascii=False),
            "confidence": j.get("confidence", 0.0),
            "factors_used": json.dumps(j.get("factors", {}), ensure_ascii=False),
            "context_snapshot": json.dumps(j.get("context", {}), ensure_ascii=False),
        })

    df = pd.DataFrame(rows)

    try:
        # 按 (stock_code, judgment_date) 去重：删除同日同标的旧记录
        for sc in stock_codes:
            memory_conn.execute(f"""
                DELETE FROM agent_judgments
                WHERE agent_id = '{AGENT_ID}'
                  AND judgment_date = DATE '{target_date}'
                  AND json_extract_string(judgment_content, '$.stock_code') = '{sc}'
            """)

        memory_conn.execute("INSERT INTO agent_judgments SELECT * FROM df")
        return len(rows)
    except Exception as e:
        log.error("写入 agent_judgments 失败: %s", e)
        return 0


# ── 主流程 ────────────────────────────────────────────────────

def observe_contraction(
    user_id: str,
    target_date: str = "",
    foundation_db: str = "",
    session_id: str = "",
    agent_memory_db: str = "",
) -> dict:
    """ContractionObserver 主入口。

    Args:
        user_id: 用户 ID
        target_date: 目标日期 (YYYY-MM-DD)，默认取最新
        foundation_db: Foundation DB 路径
        session_id: 会话 ID
        agent_memory_db: AgentMemory DB 路径

    Returns:
        AgentResult dict
    """
    ctx = AgentContext(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        user_id=user_id,
        session_id=session_id,
        target_date=target_date,
        foundation_db=foundation_db,
    )

    # 定位 Foundation DB
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

    # 定位 AgentMemory DB
    if not agent_memory_db:
        mem_path = DEFAULT_AGENT_MEMORY
    else:
        mem_path = Path(agent_memory_db)

    result = AgentResult(
        agent_id=AGENT_ID,
        agent_name=AGENT_NAME,
        status="ok",
    )

    t_start = time.time()

    try:
        conn = duckdb.connect(foundation_db, read_only=True)

        # 确定目标日期
        if not target_date:
            target_date = str(conn.execute(
                "SELECT MAX(state_date) FROM d1_perspective_state"
            ).fetchone()[0])
        log.info("目标日期: %s", target_date)

        # ── Step 1: 收缩检测 ──
        contraction_df = detect_contraction(conn, target_date)

        if contraction_df.empty:
            result.summary = f"{target_date}: 无股票触发收缩"
            result.data = {
                "date": target_date,
                "total_contraction": 0,
                "extreme_contraction": 0,
                "breakouts": [],
            }
            conn.close()
            return result.to_dict()

        # ── Step 2: 六重突破确认 ──
        breakout_results = []
        extreme_stocks = []
        judgments = []

        # 对收缩中的股票逐一评估突破
        for _, row in contraction_df.iterrows():
            stock_code = row["stock_code"]
            tf = row["timeframe"]
            is_extreme = row.get("is_extreme", False)

            if is_extreme:
                extreme_stocks.append({
                    "stock_code": stock_code,
                    "timeframe": tf,
                    "squeeze_score": int(row.get("squeeze_score", 0)),
                })

            # 只评估 D1 的突破（避免跨周期重复）
            if tf != "D1":
                continue

            # 突破评估
            breakout = evaluate_breakout(conn, stock_code, target_date, "D1")
            breakout["squeeze_score"] = int(row.get("squeeze_score", 0))
            breakout["is_extreme"] = bool(is_extreme)

            # 仅记录有意义的结果（疑似突破及以上）
            if breakout["label"] in ("确认突破", "疑似突破"):
                # Supersede 检查
                if mem_path.exists():
                    mem_conn = duckdb.connect(str(mem_path))
                    is_superseded = check_supersede(mem_conn, stock_code, target_date)
                    mem_conn.close()
                else:
                    is_superseded = False

                if not is_superseded:
                    breakout_results.append(breakout)
                    judgments.append({
                        "type": "breakout_confirmed" if breakout["label"] == "确认突破" else "breakout_suspected",
                        "content": {
                            "stock_code": stock_code,
                            "label": breakout["label"],
                            "confidence": breakout["confidence"],
                            "checks": breakout["checks"],
                            "squeeze_score": breakout["squeeze_score"],
                        },
                        "confidence": breakout["confidence"],
                        "factors": breakout["checks"],
                        "context": {
                            "target_date": target_date,
                            "timeframe": tf,
                        },
                    })

        conn.close()

        # ── Step 3: 写入 AgentMemory ──
        memory_written = 0
        if judgments and mem_path.exists():
            mem_conn = duckdb.connect(str(mem_path))
            memory_written = write_judgment(mem_conn, target_date, judgments)
            mem_conn.close()

        # 额外写入收缩统计 judgment
        if mem_path.exists() and len(contraction_df) > 0:
            mem_conn = duckdb.connect(str(mem_path))
            summary_judgment = [{
                "type": "contraction_scan",
                "content": {
                    "date": target_date,
                    "total_contraction": len(contraction_df),
                    "extreme_contraction": len(extreme_stocks),
                    "breakout_confirmed": sum(1 for b in breakout_results if b["label"] == "确认突破"),
                    "breakout_suspected": sum(1 for b in breakout_results if b["label"] == "疑似突破"),
                    "extreme_stock_list": [e["stock_code"] for e in extreme_stocks[:20]],
                },
                "confidence": 1.0,
                "factors": {},
                "context": {"target_date": target_date},
            }]
            write_judgment(mem_conn, target_date, summary_judgment)
            mem_conn.close()

        # ── Step 4: AgentBus 广播 ──
        bus_events = 0
        try:
            from hermass_platform.bus.agent_bus import AgentBus
            bus = AgentBus()

            # 极致收缩广播
            for ext in extreme_stocks[:10]:  # 限制广播数量
                bus.publish(
                    from_agent=AGENT_ID,
                    to_agent="*",
                    topic="contraction_extreme",
                    payload={
                        "stock_code": ext["stock_code"],
                        "squeeze_score": ext["squeeze_score"],
                        "timeframe": ext["timeframe"],
                    },
                    priority=1,
                )
                bus_events += 1

        except ImportError:
            log.info("AgentBus 未安装，跳过广播")
        except Exception as e:
            log.warning("AgentBus 广播异常: %s", e)

        # ── 构建 observations（供 Agent Debate 消费） ──
        observations = []
        for _, row in contraction_df.iterrows():
            stock_code = row["stock_code"]
            tf = row["timeframe"]
            is_extreme = row.get("is_extreme", False)
            # 查找该股票的突破结果
            breakout = next((b for b in breakout_results if b["stock_code"] == stock_code), None)
            observations.append({
                "stock_code": stock_code,
                "timeframe": tf,
                "is_contraction": True,
                "is_extreme": bool(is_extreme),
                "squeeze_score": int(row.get("squeeze_score", 0)),
                "bb_width_pct": float(row.get("bb_width_pct", 0) or 0),
                "has_breakout": breakout is not None,
                "breakout_label": breakout["label"] if breakout else "未突破",
                "breakout_confidence": breakout["confidence"] if breakout else 0.0,
            })

        # ── 构建结果 ──
        data = {
            "date": target_date,
            "total_contraction": len(contraction_df),
            "contraction_by_timeframe": contraction_df.groupby("timeframe").size().to_dict(),
            "extreme_contraction": len(extreme_stocks),
            "extreme_stocks": [e["stock_code"] for e in extreme_stocks[:20]],
            "breakout_results": [
                {
                    "stock_code": b["stock_code"],
                    "label": b["label"],
                    "confidence": b["confidence"],
                    "squeeze_score": b["squeeze_score"],
                    "checks": {k: v for k, v in b["checks"].items()},
                }
                for b in breakout_results[:50]
            ],
            "observations": observations,
            "memory_written": memory_written,
            "bus_events": bus_events,
        }

        confirmed = sum(1 for b in breakout_results if b["label"] == "确认突破")
        suspected = sum(1 for b in breakout_results if b["label"] == "疑似突破")

        summary = (
            f"{target_date}: 收缩 {len(contraction_df)} 只，"
            f"极致收缩 {len(extreme_stocks)} 只，"
            f"确认突破 {confirmed} 只，疑似突破 {suspected} 只。"
            f"写入 AgentMemory {memory_written} 条，广播 {bus_events} 条。"
        )

        result.data = data
        result.summary = summary

    except Exception as e:
        result.status = "error"
        result.errors.append(str(e))
        log.exception("ContractionObserver 异常")

    elapsed = time.time() - t_start
    log.info("ContractionObserver 完成 (%.1fs)", elapsed)

    return result.to_dict()


# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="ContractionObserver — 收缩突破观测")
    parser.add_argument("--date", type=str, default="", help="目标日期")
    parser.add_argument("--foundation-db", type=str, default="", help="foundation.duckdb 路径")
    parser.add_argument("--agent-memory", type=str, default="", help="AgentMemory.duckdb 路径")
    parser.add_argument("--user-id", type=str, default="cli", help="用户 ID")
    args = parser.parse_args()

    result = observe_contraction(
        user_id=args.user_id,
        target_date=args.date,
        foundation_db=args.foundation_db,
        agent_memory_db=args.agent_memory,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
