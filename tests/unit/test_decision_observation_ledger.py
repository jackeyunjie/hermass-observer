from __future__ import annotations

from datetime import date

import duckdb

from scripts import decision_observation_ledger as ledger


def test_normalize_router_dict_records_a_share_decision_observation() -> None:
    router_output = {
        "status": "ok",
        "all_routed": [
            {
                "stock_code": "000001.SZ",
                "state_hex": {"MN1": "E", "W1": "F", "D1": "E"},
                "agent_consensus": {
                    "support_agents": ["contraction_observer"],
                    "oppose_agents": ["risk_guardian"],
                },
                "risk_flags": {
                    "has_fake_breakout": True,
                    "has_overheat": False,
                },
                "final_weight": 0.72,
                "conclusion": "strong_observation",
                "action": "重点观察",
            }
        ],
    }

    records = ledger.normalize_router_records(router_output, date(2026, 6, 5))

    assert records == [
        {
            "agent": "DynamicWeightRouter",
            "judgment_type": "decision_observation",
            "stock_code": "000001.SZ",
            "chain_id": None,
            "state_date": "2026-06-05",
            "direction": "strong_observation",
            "confidence": 0.72,
            "rationale": "重点观察；final_weight=0.72；support=contraction_observer；oppose=risk_guardian",
            "risk_flags": ["has_fake_breakout"],
            "risk_veto": False,
            "key_states": {"MN1": "E", "W1": "F", "D1": "E"},
            "context": records[0]["context"],
        }
    ]
    assert records[0]["context"]["route_calculation"]["final_weight"] == 0.72


def test_write_ledger_is_idempotent_for_same_stock(tmp_path, monkeypatch) -> None:
    memory_db = tmp_path / "AgentMemory.duckdb"
    ledger_dir = tmp_path / "ledger"
    monkeypatch.setattr(ledger, "AGENT_MEMORY_DB", memory_db)
    monkeypatch.setattr(ledger, "LEDGER_DIR", ledger_dir)

    records = ledger.normalize_router_records(
        {
            "all_routed": [
                {
                    "stock_code": "000001.SZ",
                    "final_weight": 0.61,
                    "conclusion": "moderate_observation",
                    "state_hex": {"MN1": "E", "W1": "F", "D1": "C"},
                }
            ]
        },
        date(2026, 6, 5),
    )

    first = ledger.write_ledger(records, date(2026, 6, 5))
    second = ledger.write_ledger(records, date(2026, 6, 5))

    assert first["record_count"] == 1
    assert second["record_count"] == 1
    assert (ledger_dir / "observation_ledger_20260605.json").exists()

    con = duckdb.connect(str(memory_db), read_only=True)
    row = con.execute(
        """
        SELECT COUNT(*), MIN(agent_id), MIN(judgment_type), MIN(confidence)
        FROM agent_judgments
        """
    ).fetchone()
    con.close()

    assert row == (1, "DynamicWeightRouter", "decision_observation", 0.61)
