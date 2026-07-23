"""Monthly-dividend feed post: rows (yield + lights), rendering, persistence."""
import json

import pytest

import config
from src.content.llm import builtin_fake
from src.feedposts.dividend import _norm_yield, build_dividend_post, build_dividend_rows
from src.stocks.market_data import FakeMarketData
from src.storage.database import FeedPostRow, session_scope

_FAKE = ["AAPL", "JPM", "XOM", "SAP.DE", "ALV.DE"]


def test_norm_yield():
    assert _norm_yield(None) is None
    assert _norm_yield(0.9) == 0.9       # yfinance returns percent already (no ×100)
    assert _norm_yield(13.0) == 13.0
    assert _norm_yield(73.0) is None     # implausible / bad data → dropped
    assert _norm_yield(0) is None


def test_build_dividend_rows_sorted_by_yield(monkeypatch):
    monkeypatch.setattr(config, "DIVIDEND_MONTHLY_TICKERS", _FAKE)
    rows = build_dividend_rows(FakeMarketData())
    assert len(rows) == 5
    yields = [r.yield_pct for r in rows]
    assert yields == sorted(yields, reverse=True)
    assert all(r.chart_level in ("pos", "neu", "neg") for r in rows)
    assert all(r.fund_level in ("pos", "neu", "neg") for r in rows)


def test_build_dividend_post_creates_review_row(monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.setattr(config, "DIVIDEND_MONTHLY_TICKERS", _FAKE)
    pid = build_dividend_post(FakeMarketData(), builtin_fake())
    assert pid is not None
    with session_scope() as session:
        row = session.get(FeedPostRow, pid)
        assert row.status == "pending_review"
        assert row.topic_slug == "dividende-monatszahler"
        paths = json.loads(row.image_paths_json)
        assert len(paths) == 4  # hook + explainer + 1 table (5 rows) + summary
        assert all(p.endswith(".jpg") for p in paths)
        assert "anlageberatung" in row.caption.lower()


def test_build_dividend_post_too_few_data(monkeypatch):
    monkeypatch.setattr(config, "DIVIDEND_MONTHLY_TICKERS", ["AAPL"])
    assert build_dividend_post(FakeMarketData(), builtin_fake()) is None
