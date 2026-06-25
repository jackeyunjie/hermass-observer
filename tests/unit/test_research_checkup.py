from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from web.main import app
from web.main import _research_page_context


def test_research_page_context_exposes_single_stock_checkup() -> None:
    fake_cards = {
        "quick": "State：测试结构",
        "deep": "",
        "evidence": "",
        "payload": (
            '{"state_core":{"mn1_state_hex":"C","w1_state_hex":"F","d1_state_hex":"F",'
            '"ef_count":2,"state_prior_view":"多周期结构偏强"},'
            '"completeness":{"overall":"partial","state_core":"present","valuation_reference":"missing"},'
            '"strategy_fit_overlay":{"fit_strategy":"vcp","lifecycle_stage":"延展","strategy_environment_fit":"最佳适配"}}'
        ),
        "warnings": [],
        "as_of_date": "2026-06-24",
    }

    with patch("web.main._render_cards", return_value=fake_cards), \
         patch("web.main._research_lane", return_value={"lead_signal": "测试信号"}), \
         patch("web.main._strategy_rows_for_stock", return_value=[]), \
         patch("web.main._latest_unified_snapshot_rows", return_value=({}, "2026-06-24")), \
         patch("web.main._latest_industry_rotation_map", return_value=({}, "2026-06-24")):
        ctx = _research_page_context("000021.SZ", "full")

    checkup = ctx["single_stock_checkup"]
    assert checkup["title"] == "线索验证体检"
    assert checkup["tier"] in {"pass", "watch", "missing", "risk"}
    assert [item["label"] for item in checkup["items"]] == ["多周期结构", "资金确认", "行业位置", "风险底线"]
    assert checkup["items"][0]["status"] == "pass"
    assert "小红书" in checkup["next_step"]


def test_research_page_renders_single_stock_checkup() -> None:
    client = TestClient(app)
    response = client.get("/research?stock_code=000021.SZ")

    assert response.status_code == 200
    assert "线索验证体检" in response.text
    assert "把外部线索放进 Hermass 框架里核验" in response.text
