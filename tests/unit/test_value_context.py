from __future__ import annotations

from unittest.mock import patch

from web.main import _build_search_data_context, _latest_fundamental_as_of_date, _value_context_for_agent


def test_build_search_data_context_with_market_views() -> None:
    market_views = {
        "latest_report": {
            "institution": "测试机构",
            "date": "2026-05-29",
            "rating": "增持",
            "target_price": 12.3,
        },
        "rating_distribution": {"买入": 3, "增持": 2},
        "target_price_count": 5,
    }

    result = _build_search_data_context(market_views)

    assert result["status"] == "local_market_views_already_present"
    assert result["source"] == "local_market_views"
    assert result["latest_report"]["institution"] == "测试机构"
    assert result["rating_distribution"]["买入"] == 3
    assert result["target_price_count"] == 5
    assert result["digest_items"] == []
    assert result["policy_event_notes"]


def test_build_search_data_context_placeholder() -> None:
    result = _build_search_data_context({})

    assert result["status"] == "placeholder"
    assert result["latest_report"] == {}
    assert result["rating_distribution"] == {}
    assert result["target_price_count"] == 0
    assert result["digest_items"] == []
    assert result["policy_event_notes"] == []


def test_value_context_for_agent_merges_evidence_and_holders() -> None:
    fake_evidence = {
        "company_profile": {"main_business": "通信设备制造"},
        "financial_trend": {
            "period_rows": [
                {"report_period": "2025Q1", "revenue": 1230000000, "net_profit": 45600000},
                {"report_period": "2024A", "revenue": 9870000000, "net_profit": 321000000},
            ]
        },
        "market_views": {
            "latest_report": {"institution": "测试机构", "date": "2026-05-29", "rating": "增持"},
            "rating_distribution": {"增持": 2},
            "target_price_count": 1,
        },
    }
    fake_holders = [
        {
            "holder_name": "测试股东",
            "holder_type": "基金",
            "report_date": "2024-12-31",
            "share_count": 1000,
        }
    ]

    with patch("web.main._latest_fundamental_as_of_date", return_value="2026-05-29"), \
         patch("web.main.build_external_research_evidence", return_value=fake_evidence), \
         patch("web.main._load_top10_holders_context", return_value=fake_holders):
        result = _value_context_for_agent("000021.SZ")

    assert result["main_business"] == "通信设备制造"
    assert result["latest_financial_report"]["report_period"] == "2025Q1"
    assert result["annual_report_2024"]["report_period"] == "2024A"
    assert result["top10_holders"] == fake_holders
    assert result["search_data"]["status"] == "local_market_views_already_present"
    assert result["search_data"]["latest_report"]["institution"] == "测试机构"


def test_value_context_for_agent_fallback_keeps_holders() -> None:
    fake_holders = [{"holder_name": "测试股东"}]

    with patch("web.main._latest_fundamental_as_of_date", return_value="2026-05-29"), \
         patch("web.main._load_top10_holders_context", return_value=fake_holders), \
         patch("web.main.build_external_research_evidence", side_effect=RuntimeError("boom")):
        result = _value_context_for_agent("000021.SZ")

    assert result["main_business"] == ""
    assert result["latest_financial_report"] == {}
    assert result["annual_report_2024"] == {}
    assert result["top10_holders"] == fake_holders
    assert result["search_data"]["status"] == "placeholder"


def test_latest_fundamental_as_of_date_prefers_fundamental_tables() -> None:
    class FakeCon:
        def execute(self, sql: str):
            class FakeCursor:
                def __init__(self, value: str | None):
                    self._value = value

                def fetchone(self):
                    return (self._value,)

            if "ifind_industry_chain_profile" in sql:
                return FakeCursor("2026-05-21")
            if "ifind_excel_facts" in sql:
                return FakeCursor("2026-05-22")
            return FakeCursor(None)

        def close(self) -> None:
            return None

    with patch("web.main.ROOT") as mock_root, \
         patch("web.main.duckdb.connect", return_value=FakeCon()):
        mock_root.__truediv__.side_effect = lambda part: mock_root
        mock_root.exists.return_value = True
        result = _latest_fundamental_as_of_date()

    assert result == "2026-05-22"
