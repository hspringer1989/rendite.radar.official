"""Generic list-post: screens + rendering."""
import json

import pytest

import config
from src.feedposts import listposts
from src.stocks.market_data import FakeMarketData
from src.storage.database import FeedPostRow, session_scope

_FAKE = ["AAPL", "JPM", "XOM", "SAP.DE", "ALV.DE"]


def test_screen_near_52w_low_metric_format():
    rows = listposts.screen_near_52w_low(FakeMarketData(), _FAKE)
    assert len(rows) >= 3                      # those trading below their 52w high
    assert all(r.metric.startswith("-") and r.metric.endswith("%") for r in rows)
    drops = [int(r.metric[:-1]) for r in rows]
    assert drops == sorted(drops)              # most negative (biggest drop) first


def test_screen_undervalued_quality_filters_and_sorts():
    rows = listposts.screen_undervalued_quality(FakeMarketData(), _FAKE)
    assert len(rows) >= 4
    assert "AAPL" not in [r.ticker for r in rows]   # P/E 28 → excluded (>25)
    kgvs = [float(r.metric.replace(",", ".")) for r in rows]
    assert kgvs == sorted(kgvs)                     # sorted by KGV ascending


def test_build_undervalued_post_creates_review_row(monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.setattr(config, "STOCK_UNIVERSE", _FAKE)
    pid = listposts.build_undervalued_post(FakeMarketData(), scheduled_at="2030-01-01 17:00")
    assert pid is not None
    with session_scope() as session:
        row = session.get(FeedPostRow, pid)
        assert row.status == "pending_review"
        assert row.scheduled_at == "2030-01-01 17:00"
        assert len(json.loads(row.image_paths_json)) >= 4
        assert "anlageberatung" in row.caption.lower()
