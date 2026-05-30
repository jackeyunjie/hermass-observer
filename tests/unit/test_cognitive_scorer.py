import json
import tempfile
from pathlib import Path

import pytest
from hermass_platform.cognitive.cognitive_ledger import BehaviorEvent, record_event
from hermass_platform.cognitive.cognitive_scorer import compute_cognitive_scores
from hermass_platform.cognitive.cognitive_profile_builder import build_cognitive_profile


class TestCognitiveScorer:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import hermass_platform.cognitive.cognitive_ledger as cl
        self.orig_ledger_dir = cl.LEDGER_DIR
        cl.LEDGER_DIR = Path(self.tmpdir.name) / "cognitive"
        cl.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        yield
        cl.LEDGER_DIR = self.orig_ledger_dir
        self.tmpdir.cleanup()

    def _seed_events(self, user_id: str, counts: dict[str, int]):
        for event_type, count in counts.items():
            for _ in range(count):
                record_event(BehaviorEvent(user_id=user_id, event_type=event_type))

    def test_insufficient_data(self):
        self._seed_events("u_low", {"market_query": 3})
        scores = compute_cognitive_scores("u_low")
        assert scores["data_insufficient"]
        assert scores["confidence"] == 0.0

    def test_sufficient_data(self):
        self._seed_events("u_ok", {
            "market_query": 10,
            "strategy_query": 8,
            "risk_query": 5,
            "learn_query": 3,
            "industry_query": 2,
            "signal_explore": 4,
        })
        scores = compute_cognitive_scores("u_ok")
        assert not scores.get("data_insufficient", True)
        assert "dimensions" in scores
        assert len(scores["dimensions"]) == 6

    def test_dimensions_in_range(self):
        self._seed_events("u_range", {
            "market_query": 15,
            "strategy_query": 10,
            "risk_query": 5,
            "learn_query": 6,
            "signal_explore": 4,
            "industry_query": 3,
            "practice_request": 2,
        })
        scores = compute_cognitive_scores("u_range")
        for name, dim in scores["dimensions"].items():
            assert 0.0 <= dim["value"] <= 1.0, f"{name} 值超出 [0,1]: {dim['value']}"
            assert dim["level"] in ("高", "中", "中低", "低")

    def test_risk_focused_user(self):
        self._seed_events("u_risk", {
            "risk_query": 15,
            "market_query": 3,
            "strategy_query": 2,
        })
        scores = compute_cognitive_scores("u_risk")
        risk_score = scores["dimensions"]["risk_awareness"]["value"]
        strategy_score = scores["dimensions"]["strategy_awareness"]["value"]
        assert risk_score > strategy_score

    def test_confidence_increases_with_activity(self):
        self._seed_events("u_conf", {
            "market_query": 20,
            "strategy_query": 15,
            "learn_query": 10,
            "risk_query": 8,
            "signal_explore": 7,
            "industry_query": 5,
        })
        scores = compute_cognitive_scores("u_conf")
        assert scores["confidence"] > 0.2, f"自信度 {scores['confidence']} 低于阈值"

    def test_confidence_zero_insufficient(self):
        scores = compute_cognitive_scores("no_user")
        assert scores["confidence"] == 0.0


class TestCognitiveProfileBuilder:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import hermass_platform.cognitive.cognitive_ledger as cl
        self.orig_ledger_dir = cl.LEDGER_DIR
        cl.LEDGER_DIR = Path(self.tmpdir.name) / "cognitive"
        cl.LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        yield
        cl.LEDGER_DIR = self.orig_ledger_dir
        self.tmpdir.cleanup()

    def _seed(self, user_id: str, counts: dict):
        for et, c in counts.items():
            for _ in range(c):
                record_event(BehaviorEvent(user_id=user_id, event_type=et))

    def test_insufficient_profile(self):
        profile = build_cognitive_profile("no_data")
        assert profile["status"] == "insufficient_data"
        assert profile["confidence"] == 0.0
        assert profile["summary"] is not None

    def test_full_profile(self):
        self._seed("test_user", {
            "market_query": 20,
            "strategy_query": 15,
            "risk_query": 12,
            "learn_query": 10,
            "signal_explore": 8,
            "industry_query": 5,
            "practice_request": 3,
            "profile_query": 2,
        })
        profile = build_cognitive_profile("test_user")
        assert profile["status"] == "ready"
        assert profile["profile_label"] in ("策略型学习者", "风险敏感型", "策略探索者", "知识探索者", "市场观察者")
        assert len(profile["dimensions"]) == 6
        assert "summary" in profile
        assert "strengths" in profile
        assert "blind_spots" in profile
        assert profile["recommended_path"] != ""

    def test_profile_version(self):
        self._seed("v_user", {
            "market_query": 5,
            "strategy_query": 5,
            "learn_query": 5,
        })
        profile = build_cognitive_profile("v_user")
        assert profile["profile_version"] == "v1.0"
        assert "generated_at" in profile
        assert "data_period" in profile
        assert "sample_size" in profile

    def test_risk_sensitive_profile(self):
        self._seed("r_user", {
            "risk_query": 20,
            "market_query": 5,
            "strategy_query": 3,
            "learn_query": 2,
        })
        profile = build_cognitive_profile("r_user")
        assert profile["profile_label"] == "风险敏感型"

    def test_empty_user_returns_insufficient(self):
        profile = build_cognitive_profile("ghost")
        assert profile["status"] == "insufficient_data"
        assert len(profile["strengths"]) == 0
