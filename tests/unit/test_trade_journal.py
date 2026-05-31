from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hermass_platform.trade_journal import (
    _calc_pnl,
    _hex_to_state_name,
    _resolve_mn1_state_name,
    add_trade,
    delete_trade,
    get_filters,
    get_trade_stats,
    list_trades,
)
from web.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def tmp_db(tmp_path: Path):
    db = tmp_path / "trades.db"
    with patch("hermass_platform.trade_journal.DEFAULT_DB_PATH", db):
        yield db


def test_hex_to_state_name():
    assert _hex_to_state_name("E") == "天时"
    assert _hex_to_state_name("F") == "天时"
    assert _hex_to_state_name("-1") == "逆位"
    assert _hex_to_state_name("GG") == ""


def test_calc_pnl():
    class FakeRow:
        def __init__(self, entry_price, exit_price):
            self.entry_price = entry_price
            self.exit_price = exit_price

        def __getitem__(self, item):
            return getattr(self, item)

    assert round(_calc_pnl(FakeRow(10.0, 12.0)), 2) == 20.0
    assert round(_calc_pnl(FakeRow(10.0, 9.0)), 2) == -10.0
    assert _calc_pnl(FakeRow(10.0, None)) is None


def test_add_and_list_and_stats(tmp_db: Path, tmp_path: Path):
    def fake_find(target_date: str = ""):
        return tmp_path / "fake.duckdb"

    def fake_connect(*args, **kwargs):
        class FakeCon:
            def execute(self, sql, params=None):
                class FakeCursor:
                    def fetchone(self):
                        return ("E",)

                    def fetchall(self):
                        return []

                return FakeCursor()

            def close(self):
                pass
        return FakeCon()

    with patch("hermass_platform.trade_journal.find_foundation_db", side_effect=fake_find), \
         patch("hermass_platform.trade_journal.duckdb.connect", side_effect=fake_connect):
        add_trade(
            username="tester",
            trade_date="2026-05-28",
            stock_code="688107",
            stock_name="安路科技",
            direction="做多",
            entry_price=42.5,
            exit_price=48.2,
            strategy_id="vcp",
            stop_loss=39.5,
            note="test",
        )

    data = list_trades("tester")
    assert data["total"] == 1
    assert len(data["trades"]) == 1
    assert data["trades"][0]["pnl_pct"] == pytest.approx(13.4118, rel=1e-3)
    assert data["trades"][0]["strategy_label"] == "VCP 突破"

    stats = get_trade_stats("tester")
    assert stats["total_trades"] == 1
    assert stats["win_rate"] == pytest.approx(100.0)
    assert stats["max_drawdown"] == 0.0
    assert len(stats["by_strategy"]) == 1
    assert stats["by_strategy"][0]["strategy_label"] == "VCP 突破"


def test_delete_trade(tmp_db: Path):
    with patch("hermass_platform.trade_journal.DEFAULT_DB_PATH", tmp_db):
        trade = add_trade(
            username="tester",
            trade_date="2026-05-28",
            stock_code="688107",
            stock_name="安路科技",
            direction="做多",
            entry_price=42.5,
            exit_price=48.2,
            strategy_id="vcp",
            stop_loss=39.5,
        )
        assert delete_trade(trade["id"], "tester") is True
        assert delete_trade(trade["id"], "tester") is False


def test_journal_page_renders():
    client = TestClient(app)
    with patch("hermass_platform.trade_journal.list_trades", return_value={"trades": [], "total": 0, "page": 1, "pages": 1}), \
         patch("hermass_platform.trade_journal.get_trade_stats", return_value={
             "total_trades": 0,
             "win_rate": 0.0,
             "profit_factor": 0.0,
             "total_return": 0.0,
             "max_drawdown": 0.0,
             "by_strategy": [],
             "by_state": [],
             "insight": "test",
         }), \
         patch("hermass_platform.trade_journal.get_filters", return_value={"strategies": [], "states": []}):
        resp = client.get("/journal")
        assert resp.status_code == 200
        assert "交易日志" in resp.text
