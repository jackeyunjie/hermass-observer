#!/usr/bin/env python3
"""Hermass Internal Console - minimal Streamlit workbench for internal team use."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]

from hermass_platform.agents.base_agent import find_foundation_db
from hermass_platform.research import (
    build_external_research_evidence,
    format_deep_research_card,
    format_evidence_card,
    format_quick_research_card,
)


def _latest_path(pattern: str) -> Path | None:
    matches = sorted(ROOT.glob(pattern))
    return matches[-1] if matches else None


def _read_text(path: Path | None, fallback: str = "未找到") -> str:
    if not path or not path.exists():
        return fallback
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"读取失败: {exc}"


def _read_json(path: Path | None) -> dict | list | None:
    if not path or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _status_rows() -> list[tuple[str, str, str]]:
    rows = []
    candidates = [
        ("Foundation DB", find_foundation_db(str(date.today()))),
        ("Daily Brief", _latest_path("outputs/reports/daily_brief_*.md")),
        ("Strategy Ledger", _latest_path("outputs/public/strategy_signal_daily_*.json")),
        ("Forward Observation", _latest_path("outputs/public/forward_observation_*.json")),
        ("Active Alerts Ledger", ROOT / "outputs/alerts/active_state_alerts_sent.json"),
        ("Weekly Recap Spec", ROOT / "docs/WEEKLY_COGNITIVE_RECAP_SPEC.md"),
    ]
    for label, value in candidates:
        path = Path(value) if value else None
        if path and path.exists():
            rows.append((label, "OK", str(path.relative_to(ROOT))))
        else:
            rows.append((label, "Missing", "-"))
    return rows


def _render_status_panel() -> None:
    st.subheader("Daily Outputs")
    rows = _status_rows()
    st.table([{"item": item, "status": status, "path": path} for item, status, path in rows])


def _render_research_panel() -> None:
    st.subheader("Research Card Preview")
    col1, col2 = st.columns([2, 1])
    with col1:
        stock_code = st.text_input("Stock Code", value="000021.SZ")
    with col2:
        render_profile = st.selectbox("Deep Profile", ["standard", "full"], index=1)

    if st.button("Generate Research Cards", type="primary"):
        foundation_db = find_foundation_db(str(date.today()))
        if not foundation_db:
            st.error("未找到 foundation DB。")
            return
        evidence = build_external_research_evidence(
            stock_code=stock_code.strip().upper(),
            as_of_date=str(date.today()),
            foundation_db=foundation_db,
        )
        tabs = st.tabs(["Quick", "Deep", "Evidence", "Payload"])
        with tabs[0]:
            st.code(format_quick_research_card(evidence), language="markdown")
        with tabs[1]:
            st.code(format_deep_research_card(evidence, render_profile=render_profile), language="markdown")
        with tabs[2]:
            st.code(format_evidence_card(evidence), language="markdown")
        with tabs[3]:
            st.json(evidence)


def _render_push_panel() -> None:
    st.subheader("Push Outputs")
    alert_ledger = _read_json(ROOT / "outputs/alerts/active_state_alerts_sent.json")
    if alert_ledger:
        st.markdown("**Active Alert Ledger**")
        st.json(alert_ledger)
    else:
        st.info("暂无主动提醒账本。")

    latest_weekly = _read_text(_latest_path("outputs/cognitive/weekly_recap_*.md"), fallback="暂无周复盘文件。")
    st.markdown("**Weekly Recap Snapshot**")
    st.code(latest_weekly, language="markdown")


def _render_runtime_panel() -> None:
    st.subheader("Runtime Status")
    cron_config = _read_json(ROOT / "config/hermes_cron.json")
    if cron_config:
        st.markdown("**Cron Jobs**")
        jobs = cron_config.get("jobs", [])
        st.table(
            [
                {
                    "name": job.get("name", ""),
                    "schedule": job.get("cron", ""),
                    "enabled": job.get("enabled", True),
                }
                for job in jobs
            ]
        )
    else:
        st.info("无法读取 cron 配置。")


def main() -> None:
    st.set_page_config(page_title="Hermass Internal Console", page_icon="H", layout="wide")
    st.title("Hermass Internal Console")
    st.caption("Internal team workbench: outputs, research cards, alerts, and runtime status.")

    tab1, tab2, tab3, tab4 = st.tabs(["Outputs", "Research", "Push", "Runtime"])
    with tab1:
        _render_status_panel()
    with tab2:
        _render_research_panel()
    with tab3:
        _render_push_panel()
    with tab4:
        _render_runtime_panel()


if __name__ == "__main__":
    main()
