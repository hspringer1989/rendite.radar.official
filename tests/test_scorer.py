import json

from src.content.llm import FakeLLM
from src.content.scorer import score_trends
from src.models import TrendItem


def _trends(n):
    return [TrendItem(source="rss", title=f"Thema {i}") for i in range(n)]


def test_scores_parsed_and_weighted():
    llm = FakeLLM({"score_trends": json.dumps([
        {"i": 0, "viral": 1.0, "fit": 1.0, "monetization": 1.0, "reasoning": "top"},
        {"i": 1, "viral": 0.4, "fit": 0.8, "monetization": 0.2},
    ])})
    scores = score_trends(_trends(2), llm)
    assert scores[0].total == 1.0
    assert scores[1].total == round(0.45 * 0.4 + 0.30 * 0.8 + 0.25 * 0.2, 4)
    assert scores[0].reasoning == "top"


def test_out_of_range_values_clamped():
    llm = FakeLLM({"score_trends": json.dumps([
        {"i": 0, "viral": 1.7, "fit": -0.3, "monetization": 0.5},
    ])})
    score = score_trends(_trends(1), llm)[0]
    assert score.viral_potential == 1.0
    assert score.niche_fit == 0.0


def test_invalid_json_yields_none_scores():
    llm = FakeLLM({"score_trends": "Sorry, hier ist meine Einschätzung als Text..."})
    assert score_trends(_trends(3), llm) == [None, None, None]


def test_bogus_indexes_ignored():
    llm = FakeLLM({"score_trends": json.dumps([
        {"i": 99, "viral": 0.9, "fit": 0.9, "monetization": 0.9},
        {"i": "x", "viral": 0.9, "fit": 0.9, "monetization": 0.9},
    ])})
    assert score_trends(_trends(2), llm) == [None, None]
