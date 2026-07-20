"""Story pipeline + review decision. Card rendering is skipped if Pillow is absent."""
import json

import pytest

import config
from src.content.llm import FakeLLM
from src.review.telegram_bot import apply_story_decision
from src.stocks.market_data import FakeMarketData
from src.storage.database import StoryRow, session_scope

pytest.importorskip("PIL", reason="Pillow not installed — card rendering unavailable")


def _fake_llm() -> FakeLLM:
    return FakeLLM({"stock_analysis": json.dumps({"candidates": [], "overall": ""})})


def _configure(monkeypatch):
    monkeypatch.setattr(config, "STOCK_UNIVERSE", ["AAPL", "JPM", "XOM"])
    monkeypatch.setattr(config, "STOCK_CANDIDATES_COUNT", 3)


def test_build_daily_stories_creates_cards(monkeypatch):
    _configure(monkeypatch)
    from src.stocks.pipeline import build_daily_stories

    ids = build_daily_stories(FakeMarketData(), _fake_llm())
    # earnings + overview + 3 candidates
    assert len(ids) == 5
    with session_scope() as session:
        kinds = [session.get(StoryRow, i).kind for i in ids]
    assert kinds[0] == "earnings"
    assert kinds[1] == "candidates"
    assert kinds[2:] == ["candidate", "candidate", "candidate"]


def test_story_cards_are_pending_review_and_written(monkeypatch):
    _configure(monkeypatch)
    from src.stocks.pipeline import build_daily_stories

    ids = build_daily_stories(FakeMarketData(), _fake_llm())
    with session_scope() as session:
        for i in ids:
            row = session.get(StoryRow, i)
            assert row.status == "pending_review"
            assert row.image_path.endswith(".jpg")


def test_story_decision_approve_and_reject(monkeypatch):
    _configure(monkeypatch)
    from src.stocks.pipeline import build_daily_stories

    ids = build_daily_stories(FakeMarketData(), _fake_llm())
    assert apply_story_decision(ids[0], "approve")
    assert apply_story_decision(ids[1], "reject")
    with session_scope() as session:
        assert session.get(StoryRow, ids[0]).status == "approved"
        assert session.get(StoryRow, ids[1]).status == "rejected"


def test_story_decision_double_is_refused(monkeypatch):
    _configure(monkeypatch)
    from src.stocks.pipeline import build_daily_stories

    ids = build_daily_stories(FakeMarketData(), _fake_llm())
    apply_story_decision(ids[0], "approve")
    ack = apply_story_decision(ids[0], "reject")
    assert "bereits" in ack
