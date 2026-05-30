#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agently_adapter import a_share_actions
from agently_adapter import stockpool_daily_runner
from agently_adapter.agently_a_share_flow import build_flow, sanitize_import_path
from hermass_platform.research.external_research_evidence import build_external_research_evidence
from hermass_platform.research.external_research_formatters import (
    RENDER_PROFILES,
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)


class RunDailyRequest(BaseModel):
    date: str = Field(..., description="交易日，格式 YYYY-MM-DD")
    previous_date: str = Field(..., description="前一交易日，格式 YYYY-MM-DD")
    foundation_db: str = Field(..., description="Foundation DB 输出路径")
    boundary_pct: float = Field(0.03, description="State cache SR boundary threshold")
    lookback_days: int = Field(20, description="Strategy evidence lookback days")
    min_ef: int = Field(2, description="Minimum E/F cycles for signal ledger")
    windows: str = Field("5,10,20", description="Forward observation windows")
    timeout: float = Field(1800.0, description="Per-step command timeout in seconds")
    auto_close_timeout: float = Field(1.0, description="Agently execution idle auto-close timeout")


class GenerateBriefRequest(BaseModel):
    date: str = Field(..., description="交易日，格式 YYYY-MM-DD")


class RunFullDailyRequest(BaseModel):
    date: str = Field(..., description="交易日，格式 YYYY-MM-DD")
    previous_date: str = Field(..., description="前一交易日，格式 YYYY-MM-DD")
    foundation_db: str | None = Field(None, description="可选，Foundation DB 输出路径")
    download: bool = Field(False, description="是否先下载 Blackwolf 日线压缩包")
    build_raw: bool = Field(False, description="是否构建 P108 原始 DuckDB")
    download_moneyflow: bool = Field(False, description="是否下载并导入近期资金流")
    moneyflow_days: int = Field(1, description="资金流下载交易日天数")
    build_foundation: bool = Field(False, description="是否从原始库重建 Foundation DB")


class ResearchRequest(BaseModel):
    stock_code: str = Field(..., description="股票代码，例如 600519 或 600519.SH")
    date: str = Field(..., description="查询日期，格式 YYYY-MM-DD")
    foundation_db: str | None = Field(None, description="可选，Foundation DB 覆盖路径")
    fundamental_db: str | None = Field(None, description="可选，fundamental_evidence.duckdb 覆盖路径")
    render_profile: str = Field("full", description="deep card 展开层级：standard / full / value")


app = FastAPI(
    title="Hermass A-share Service",
    version="0.2.0",
    description="A-share-only read-only service exposing both the core flow and the full compatibility workflow.",
)


def _signal_payload_path(date_str: str | None = None) -> Path:
    if date_str:
        return ROOT / "outputs" / "strategy_signals" / f"strategy_signal_daily_{date_str.replace('-', '')}.json"
    return ROOT / "outputs" / "strategy_signals" / "strategy_signal_daily_latest.json"


def _load_signal_payload(date_str: str | None = None) -> dict[str, Any]:
    path = _signal_payload_path(date_str)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"signal payload not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid signal payload JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"unexpected signal payload type: {type(payload).__name__}")
    return payload


@app.on_event("startup")
def startup() -> None:
    sanitize_import_path()
    os.environ.setdefault("HERMASS_LLM_MODEL", "deepseekV4")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "scope": "a_share_only",
        "research_only": True,
        "service": "hermass-a-share-service",
    }


@app.post("/run-daily")
def run_daily(req: RunDailyRequest) -> dict[str, Any]:
    flow = build_flow()
    payload = {
        "date": req.date,
        "previous_date": req.previous_date,
        "foundation_db": req.foundation_db,
        "boundary_pct": req.boundary_pct,
        "lookback_days": req.lookback_days,
        "min_ef": req.min_ef,
        "windows": req.windows,
        "command_timeout": req.timeout,
    }
    execution = flow.create_execution(auto_close=True, auto_close_timeout=req.auto_close_timeout)
    return execution.start(payload, timeout=None)


@app.post("/run-full-daily")
def run_full_daily(req: RunFullDailyRequest) -> dict[str, Any]:
    return stockpool_daily_runner.run_full_workflow(
        req.date,
        req.previous_date,
        req.foundation_db,
        download=req.download,
        build_raw=req.build_raw,
        download_moneyflow_flag=req.download_moneyflow,
        moneyflow_days=req.moneyflow_days,
        build_foundation_flag=req.build_foundation,
    )


@app.post("/generate-brief")
def generate_brief(req: GenerateBriefRequest) -> dict[str, Any]:
    return a_share_actions.build_daily_brief(req.date)


@app.get("/query-signal")
def query_signal(
    stock_code: str = Query(..., description="股票代码，例如 600519"),
    date: str | None = Query(None, description="可选，YYYY-MM-DD；默认 latest"),
) -> dict[str, Any]:
    payload = _load_signal_payload(date)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise HTTPException(status_code=500, detail="signal payload missing rows")
    matched = [row for row in rows if isinstance(row, dict) and row.get("stock_code") == stock_code]
    return {
        "ok": True,
        "scope": "a_share_only",
        "date": payload.get("date"),
        "stock_code": stock_code,
        "count": len(matched),
        "rows": matched,
        "research_only": True,
    }


@app.post("/research/evidence")
def research_evidence(req: ResearchRequest) -> dict[str, Any]:
    payload = build_external_research_evidence(
        stock_code=req.stock_code,
        as_of_date=req.date,
        foundation_db=req.foundation_db,
        fundamental_db=req.fundamental_db,
    )
    return {
        "ok": True,
        "scope": "a_share_only",
        "research_only": True,
        "kind": "external_research_evidence",
        "payload": payload,
    }


@app.post("/research/card/quick")
def research_quick_card(req: ResearchRequest) -> dict[str, Any]:
    evidence = build_external_research_evidence(
        stock_code=req.stock_code,
        as_of_date=req.date,
        foundation_db=req.foundation_db,
        fundamental_db=req.fundamental_db,
    )
    return {
        "ok": True,
        "scope": "a_share_only",
        "research_only": True,
        "kind": "quick_research_card",
        "stock_code": evidence.get("meta", {}).get("stock_code", req.stock_code),
        "date": req.date,
        "completeness": evidence.get("completeness", {}),
        "card_markdown": format_quick_research_card(evidence),
    }


@app.post("/research/card/deep")
def research_deep_card(req: ResearchRequest) -> dict[str, Any]:
    render_profile = req.render_profile if req.render_profile in RENDER_PROFILES else "full"
    evidence = build_external_research_evidence(
        stock_code=req.stock_code,
        as_of_date=req.date,
        foundation_db=req.foundation_db,
        fundamental_db=req.fundamental_db,
    )
    return {
        "ok": True,
        "scope": "a_share_only",
        "research_only": True,
        "kind": "deep_research_card",
        "stock_code": evidence.get("meta", {}).get("stock_code", req.stock_code),
        "date": req.date,
        "render_profile": render_profile,
        "completeness": evidence.get("completeness", {}),
        "card_markdown": format_deep_research_card(evidence, render_profile=render_profile),
    }


@app.post("/research/card/evidence")
def research_evidence_card(req: ResearchRequest) -> dict[str, Any]:
    evidence = build_external_research_evidence(
        stock_code=req.stock_code,
        as_of_date=req.date,
        foundation_db=req.foundation_db,
        fundamental_db=req.fundamental_db,
    )
    return {
        "ok": True,
        "scope": "a_share_only",
        "research_only": True,
        "kind": "evidence_research_card",
        "stock_code": evidence.get("meta", {}).get("stock_code", req.stock_code),
        "date": req.date,
        "completeness": evidence.get("completeness", {}),
        "card_markdown": format_evidence_card(evidence),
    }


def main() -> int:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Hermass A-share FastAPI service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run("hermass_platform.api.a_share_service:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
