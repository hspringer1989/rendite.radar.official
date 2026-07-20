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
    return FakeLLM({"stock_analysis": json.dumps({"candidates": []})})


def _configure(monkeypatch):
    monkeypatch.setattr(config, "STOCK_UNIVERSE", ["AAPL", "JPM", "XOM"])
    monkeypatch.setattr(config, "STOCK_CANDIDATES_COUNT", 3)


def _build(monkeypatch):
    _configure(monkeypatch)
    from src.stocks.pipeline import build_daily_stories

    return build_daily_stories(FakeMarketData(), _fake_llm())


def test_build_creates_earnings_overview_and_three_cards_per_candidate(monkeypatch):
    ids = _build(monkeypatch)
    # earnings(1) + overview(1) + 3 candidates × 3 cards = 11
    assert len(ids) == 11
    with session_scope() as session:
        rows = [session.get(StoryRow, i) for i in ids]
    assert rows[0].kind == "earnings"
    assert rows[1].kind == "candidates"
    cand = rows[2:]
    assert all(r.kind == "candidate" for r in cand)
    # each candidate contributes exactly the three parts
    parts = sorted(r.part for r in cand[:3])
    assert parts == ["chart", "fundamental", "overall"]


def test_story_cards_are_pending_review_and_written(monkeypatch):
    ids = _build(monkeypatch)
    with session_scope() as session:
        for i in ids:
            row = session.get(StoryRow, i)
            assert row.status == "pending_review"
            assert row.image_path.endswith(".jpg")


def test_candidate_decision_cascades_to_whole_ticker(monkeypatch):
    from sqlalchemy import select

    ids = _build(monkeypatch)
    with session_scope() as session:
        first = session.execute(
            select(StoryRow).where(StoryRow.kind == "candidate").order_by(StoryRow.id)
        ).scalars().first()
        ticker = first.ticker
        group = [r.id for r in session.execute(
            select(StoryRow).where(StoryRow.ticker == ticker)
        ).scalars().all()]
    assert len(group) == 3  # chart + fundamental + overall
    # approving any one card approves all three of that ticker
    assert apply_story_decision(group[0], "approve")
    with session_scope() as session:
        for gid in group:
            assert session.get(StoryRow, gid).status == "approved"


def test_earnings_decision_is_single(monkeypatch):
    ids = _build(monkeypatch)
    assert apply_story_decision(ids[0], "approve")   # earnings
    ack = apply_story_decision(ids[0], "reject")
    assert "bereits" in ack
