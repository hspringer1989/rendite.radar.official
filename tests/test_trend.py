"""News-driven Trend-Aktie: selection, single-ticker analysis, cooldown, posting."""
from pathlib import Path

import pytest

import config
from src.content.llm import builtin_fake
from src.publish import instagram
from src.stocks import news_trend
from src.stocks.analyzer import build_candidate_for_ticker
from src.stocks.market_data import FakeMarketData
from src.stocks.pipeline import (
    _persist_candidate_cards,
    _recent_candidate_tickers,
    _today_local,
    publish_next_candidate_group,
)
from src.storage.database import StoryRow, session_scope

_TODAY = _today_local().strftime("%Y-%m-%d")


# ── selection ──────────────────────────────────────────────────────────────
def test_pick_trend_ticker():
    res = news_trend.pick_trend_ticker(["Exxon meldet Zahlen"], builtin_fake(), set())
    assert res is not None and res[0] == "XOM"


def test_select_trend_ticker_validates_and_excludes(monkeypatch):
    monkeypatch.setattr(news_trend, "gather_headlines", lambda limit=60: ["Schlagzeile"])
    md = FakeMarketData()
    assert news_trend.select_trend_ticker(md, builtin_fake(), set())[0] == "XOM"
    # excluded ticker → None (the fake keeps offering XOM, which stays blocked)
    assert news_trend.select_trend_ticker(md, builtin_fake(), {"XOM"}) is None


def test_select_trend_ticker_no_headlines(monkeypatch):
    monkeypatch.setattr(news_trend, "gather_headlines", lambda limit=60: [])
    assert news_trend.select_trend_ticker(FakeMarketData(), builtin_fake(), set()) is None


# ── single-ticker analysis ─────────────────────────────────────────────────
def test_build_candidate_for_ticker():
    c = build_candidate_for_ticker(FakeMarketData(), "XOM", builtin_fake(),
                                   category="TREND-AKTIE", trend_reason="im Fokus")
    assert c is not None
    assert c.category == "TREND-AKTIE" and c.trend_reason == "im Fokus"
    assert c.chart_text and c.stop_loss < c.entry < c.take_profit


def test_build_candidate_for_ticker_unknown():
    assert build_candidate_for_ticker(FakeMarketData(), "ZZZZ", builtin_fake()) is None


# ── cooldown (shared across candidate + trend) ─────────────────────────────
def test_cooldown_includes_trend_kind():
    with session_scope() as session:
        session.add(StoryRow(kind="trend", ticker="AAPL", trade_date=_TODAY, status="published"))
    assert "AAPL" in _recent_candidate_tickers(30)


# ── persist + post ─────────────────────────────────────────────────────────
def test_persist_trend_cards():
    pytest.importorskip("PIL")
    c = build_candidate_for_ticker(FakeMarketData(), "XOM", builtin_fake(), category="TREND-AKTIE")
    ids = _persist_candidate_cards(c, Path(config.STORY_DIR), _TODAY, kind="trend")
    assert len(ids) == 3
    with session_scope() as session:
        assert all(session.get(StoryRow, i).kind == "trend" for i in ids)


async def test_publish_trend_group(monkeypatch):
    pytest.importorskip("PIL")

    async def _fake_story(_path):
        return "IG_TREND"
    monkeypatch.setattr(instagram, "publish_story", _fake_story)

    c = build_candidate_for_ticker(FakeMarketData(), "XOM", builtin_fake(), category="TREND-AKTIE")
    ids = _persist_candidate_cards(c, Path(config.STORY_DIR), _TODAY, kind="trend")
    with session_scope() as session:
        for i in ids:
            session.get(StoryRow, i).status = "approved"
    posted = await publish_next_candidate_group(market="US", kind="trend")  # XOM is US
    assert set(posted) == set(ids)
