import pytest
from hermass_platform.agents.coach import (
    KNOWLEDGE_BASE,
    search_knowledge,
    get_learning_path,
    get_concept,
    get_topic_list,
    generate_quiz,
    PRACTICE_QUESTIONS,
)


class TestCoachKnowledgeBase:

    def test_all_topics_have_concepts(self):
        for topic, data in KNOWLEDGE_BASE.items():
            assert len(data["concepts"]) > 0, f"主题 {topic} 无内容"
            for c in data["concepts"]:
                assert "name" in c
                assert "answer" in c
                assert len(c["answer"]) > 50, f"{topic}/{c['name']} 答案太短"

    def test_at_least_6_topics(self):
        assert len(KNOWLEDGE_BASE) >= 6

    def test_practice_questions_cover_multiple_topics(self):
        topics = {q["topic"] for q in PRACTICE_QUESTIONS}
        assert len(topics) >= 3


class TestSearchKnowledge:

    def test_search_state(self):
        results = search_knowledge(["State", "是什么"])
        assert len(results) > 0
        assert results[0]["relevance"] > 0

    def test_search_vcp(self):
        results = search_knowledge(["VCP", "突破"])
        assert len(results) > 0
        assert any("VCP" in r["answer"] for r in results)

    def test_search_2560(self):
        results = search_knowledge(["2560", "出场"])
        assert len(results) > 0

    def test_search_empty_keywords(self):
        results = search_knowledge([])
        assert results == []

    def test_search_nonexistent(self):
        results = search_knowledge(["火星单词"])
        assert results == []

    def test_search_results_sorted_by_relevance(self):
        results = search_knowledge(["E", "F", "State"])
        if len(results) >= 2:
            assert results[0]["relevance"] >= results[1]["relevance"]

    def test_max_5_results(self):
        results = search_knowledge(["策略"])
        assert len(results) <= 5


class TestGetConcept:

    def test_get_known_concept(self):
        answer = get_concept("state", "State 是什么")
        assert answer is not None
        assert len(answer) > 0

    def test_get_ef_concept(self):
        answer = get_concept("state", "E 和 F 状态的含义")
        assert answer is not None
        assert "14" in answer or "15" in answer

    def test_get_nonexistent_topic(self):
        assert get_concept("nonexistent", "test") is None

    def test_get_nonexistent_concept(self):
        assert get_concept("state", "不存在的概念") is None


class TestGetTopicList:

    def test_topic_list(self):
        topics = get_topic_list()
        assert len(topics) >= 6
        for t in topics:
            assert "topic" in t
            assert "title" in t
            assert "concept_count" in t
            assert t["concept_count"] > 0


class TestLearningPath:

    def test_default_learning_path(self):
        path = get_learning_path()
        assert len(path) >= 4
        for phase in path:
            assert "phase" in phase
            assert "title" in phase
            assert "description" in phase

    def test_personalized_low_risk(self):
        profile = {"dimensions": {"risk_awareness": {"value": 0.2}}}
        path = get_learning_path(profile)
        assert any("风控" in p["title"] or "风险" in p["title"] for p in path)

    def test_personalized_low_strategy(self):
        profile = {"dimensions": {"strategy_awareness": {"value": 0.2}}}
        path = get_learning_path(profile)
        assert any("策略" in p["title"] for p in path)

    def test_personalized_high_both(self):
        profile = {
            "dimensions": {
                "risk_awareness": {"value": 0.8},
                "strategy_awareness": {"value": 0.9},
            }
        }
        path = get_learning_path(profile)
        assert len(path) >= 4


class TestGenerateQuiz:

    def test_default_quiz(self):
        questions = generate_quiz()
        assert len(questions) == 3
        for q in questions:
            assert "question" in q
            assert "hint" in q
            assert "answer" in q

    def test_topic_filtered_quiz(self):
        questions = generate_quiz(topic="state")
        assert len(questions) >= 1
        for q in questions:
            assert "question" in q
            assert len(q["answer"]) > 0

    def test_count_limit(self):
        questions = generate_quiz(count=1)
        assert len(questions) == 1

    def test_count_exceeds_pool(self):
        questions = generate_quiz(count=100)
        assert len(questions) <= len(PRACTICE_QUESTIONS)

    def test_quiz_structure(self):
        questions = generate_quiz(count=3)
        for q in questions:
            assert "question" in q
            assert isinstance(q["question"], str)
            assert len(q["hint"]) > 0
            assert len(q["answer"]) > 0
