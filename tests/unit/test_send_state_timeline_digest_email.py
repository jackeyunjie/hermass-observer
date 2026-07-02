"""Tests for scripts/send_state_timeline_digest_email.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.send_state_timeline_digest_email import (
    _change_strength,
    _compute_extra_changes,
    _dispatch_subscriptions,
    _escape_html,
    _fmt_delta,
    _latest_rows_for_anchor_date,
    _load_subscriptions,
    build_html,
)


def make_row(**overrides: Any) -> dict[str, Any]:
    defaults = {
        "stock_code": "000001.SZ",
        "stock_name": "平安银行",
        "industry_l1": "银行",
        "state_date": "2026-07-01",
        "mn1_state_hex": "E",
        "w1_state_hex": "E",
        "d1_state_hex": "F",
        "state_triplet": "E/E/F",
        "mn1_is_ef": True,
        "w1_is_ef": True,
        "d1_is_ef": True,
        "mn1_is_ab": False,
        "w1_is_ab": False,
        "d1_is_ab": False,
        "mn1_is_zero": False,
        "w1_is_zero": False,
        "d1_is_zero": False,
        "ef_count": 3,
        "ef_pattern": "MN1+W1+D1",
        "ab_count": 0,
        "ab_pattern": "-",
        "zero_count": 0,
        "zero_pattern": "-",
        "state_change_flag": True,
        "ef_change": 1,
        "transition_label": "E/E/E -> E/E/F",
        "close": 12.34,
    }
    defaults.update(overrides)
    return defaults


def test_compute_extra_changes_fills_ab_zero() -> None:
    rows = [
        make_row(stock_code="A", state_date="2026-07-01", ab_count=2, zero_count=1, ef_change=1),
        make_row(stock_code="A", state_date="2026-06-30", ab_count=1, zero_count=1, ef_change=0),
    ]
    latest = _compute_extra_changes(rows)
    assert len(latest) == 1
    assert latest[0]["ab_change"] == 1
    assert latest[0]["zero_change"] == 0


def test_compute_extra_changes_none_when_single_row() -> None:
    rows = [make_row(stock_code="A", ab_count=1, zero_count=1)]
    latest = _compute_extra_changes(rows)
    assert len(latest) == 1
    assert latest[0]["ab_change"] is None
    assert latest[0]["zero_change"] is None


def test_latest_rows_for_anchor_date_keeps_previous_day_for_change_calc() -> None:
    rows = [
        make_row(stock_code="A", state_date="2026-07-01", ab_count=2, zero_count=1),
        make_row(stock_code="A", state_date="2026-06-30", ab_count=1, zero_count=0),
        make_row(stock_code="B", state_date="2026-06-30", ab_count=3, zero_count=2),
    ]
    latest = _latest_rows_for_anchor_date(rows, "2026-07-01")
    assert len(latest) == 1
    assert latest[0]["stock_code"] == "A"
    assert latest[0]["ab_change"] == 1
    assert latest[0]["zero_change"] == 1


def test_change_strength_combines_deltas() -> None:
    row = {"ef_change": 2, "ab_change": -1, "zero_change": 0}
    assert _change_strength(row) == 3


def test_fmt_delta() -> None:
    assert _fmt_delta(3) == "+3"
    assert _fmt_delta(-2) == "-2"
    assert _fmt_delta(0) == "0"
    assert _fmt_delta(None) == "-"


def test_escape_html() -> None:
    assert _escape_html("<script>") == "&lt;script&gt;"
    assert _escape_html(None) == ""


def test_build_html_contains_required_sections() -> None:
    latest = [
        make_row(stock_code="000001.SZ", mn1_is_ef=True, w1_is_ef=True, d1_is_ef=True),
        make_row(stock_code="000002.SZ", mn1_is_ab=True, ab_count=1, ef_count=0),
        make_row(stock_code="000003.SZ", d1_is_zero=True, zero_count=1, ef_count=0, ab_count=0),
    ]
    changed = sorted(latest, key=_change_strength, reverse=True)
    html = build_html("2026-07-01", latest, changed, [])

    assert "State Timeline Observer 每日摘要" in html
    assert "2026-07-01" in html
    assert "仅作研究观察，不构成交易建议" in html
    assert "console.supertrader.world/state-observer" in html
    assert "🔥 今日状态变化最大 Top20" in html
    assert "📈 月线 EF" in html
    assert "📈 周线 EF" in html
    assert "📈 日线 EF" in html
    assert "📊 月线 A/B" in html
    assert "📊 周线 A/B" in html
    assert "📊 日线 A/B" in html
    assert "🎯 月线 0" in html
    assert "🎯 周线 0" in html
    assert "🎯 日线 0" in html


def test_build_html_no_forbidden_terms() -> None:
    latest = [make_row()]
    html = build_html("2026-07-01", latest, latest, [])
    forbidden = ["买入", "卖出", "止损", "止盈", "目标价", "收益承诺"]
    for term in forbidden:
        assert term not in html, f"forbidden term found: {term}"


def test_build_html_empty_data() -> None:
    html = build_html("2026-07-01", [], [], [])
    assert "State Timeline Observer 每日摘要" in html
    assert "今日无状态变化" in html


def test_build_html_watchlist_section() -> None:
    latest = [make_row()]
    watchlist = [
        make_row(stock_code="000021.SZ", stock_name="深科技", state_date="2026-07-01"),
    ]
    html = build_html("2026-07-01", latest, latest, watchlist)
    assert "自选池最近 3 天变化" in html
    assert "000021.SZ" in html
    assert "深科技" in html


def _write_temp_ledger(tmp_path: Path, tasks: list[dict[str, Any]]) -> Path:
    path = tmp_path / "test_subscriptions.json"
    path.write_text(json.dumps({"version": "1.0.0", "tasks": tasks}, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_subscriptions_filters_active_digest(tmp_path: Path) -> None:
    ledger = _write_temp_ledger(
        tmp_path,
        [
            {
                "task_id": "digest_001",
                "task_type": "state_timeline_digest",
                "email": "a@example.com",
                "symbol_set": "top50",
                "days": 2,
                "status": "active",
                "created_by": "",
            },
            {
                "task_id": "digest_002",
                "task_type": "state_timeline_digest",
                "email": "b@example.com",
                "symbol_set": "all",
                "days": 3,
                "status": "cancelled",
                "created_by": "",
            },
        ],
    )
    subs = _load_subscriptions(ledger)
    assert len(subs) == 1
    assert subs[0]["task_id"] == "digest_001"
    assert subs[0]["email"] == "a@example.com"


def test_load_subscriptions_ignores_other_task_types(tmp_path: Path) -> None:
    ledger = _write_temp_ledger(
        tmp_path,
        [
            {
                "task_id": "watch_001",
                "task_type": "watch_command",
                "email": "a@example.com",
                "status": "active",
            },
            {
                "task_id": "digest_001",
                "task_type": "state_timeline_digest",
                "email": "b@example.com",
                "symbol_set": "top50",
                "days": 2,
                "status": "active",
                "created_by": "",
            },
        ],
    )
    subs = _load_subscriptions(ledger)
    assert len(subs) == 1
    assert subs[0]["task_id"] == "digest_001"


def test_dispatch_subscriptions_dry_with_real_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = _write_temp_ledger(
        tmp_path,
        [
            {
                "task_id": "digest_top50",
                "task_type": "state_timeline_digest",
                "email": "to@example.com",
                "symbol_set": "top50",
                "days": 2,
                "status": "active",
                "created_by": "",
            },
        ],
    )
    rc = _dispatch_subscriptions("2026-07-02", dry=True, ledger_path=ledger)
    captured = capsys.readouterr()
    assert rc == 0
    assert "[DISPATCH OK 1/1]" in captured.out
    assert "派发完成: 1/1 成功" in captured.out
    assert "State Timeline Observer 每日摘要" in captured.out
