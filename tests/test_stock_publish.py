"""Story posting queue — publish_story is faked, no network."""
from src.publish import instagram
from src.stocks.pipeline import (
    _today_local,
    publish_next_candidate_group,
    publish_next_story,
)
from src.storage.database import StoryRow, session_scope

_TODAY = _today_local().strftime("%Y-%m-%d")


def _make_story(kind: str, market: str = "", status: str = "approved",
                trade_date: str = _TODAY, ticker: str = "", part: str = "") -> int:
    with session_scope() as session:
        row = StoryRow(kind=kind, market=market, image_path="card.jpg",
                       status=status, trade_date=trade_date, ticker=ticker, part=part)
        session.add(row)
        session.flush()
        return row.id


def _fake_publish(monkeypatch, media_id: str = "IG_MEDIA_1"):
    async def _pub(_image_path: str) -> str:
        return media_id
    monkeypatch.setattr(instagram, "publish_story", _pub)


def _candidate_group(ticker: str, market: str, status: str = "approved") -> list[int]:
    return [_make_story("candidate", market, status, ticker=ticker, part=p)
            for p in ("chart", "fundamental", "overall")]


# ── single stories (earnings / overview) ───────────────────────────────────
async def test_publish_next_story_marks_published(monkeypatch):
    _fake_publish(monkeypatch)
    sid = _make_story("earnings")
    assert await publish_next_story(kinds=["earnings"]) == sid
    with session_scope() as session:
        row = session.get(StoryRow, sid)
        assert row.status == "published"
        assert row.ig_media_id == "IG_MEDIA_1"


async def test_returns_none_when_nothing_approved(monkeypatch):
    _fake_publish(monkeypatch)
    _make_story("earnings", status="pending_review")
    assert await publish_next_story(kinds=["earnings"]) is None


async def test_stale_story_from_previous_day_is_not_posted(monkeypatch):
    _fake_publish(monkeypatch)
    _make_story("earnings", trade_date="2000-01-01")
    assert await publish_next_story(kinds=["earnings"]) is None


# ── candidate groups (3 cards per ticker) ──────────────────────────────────
async def test_group_posts_all_three_parts(monkeypatch):
    _fake_publish(monkeypatch)
    group = _candidate_group("JPM", "US")
    posted = await publish_next_candidate_group(market="US")
    assert set(posted) == set(group)
    with session_scope() as session:
        assert all(session.get(StoryRow, i).status == "published" for i in group)


async def test_group_market_filter(monkeypatch):
    _fake_publish(monkeypatch)
    eu = _candidate_group("SAP.DE", "EU")
    _candidate_group("JPM", "US")
    posted = await publish_next_candidate_group(market="US")
    assert all(pid not in eu for pid in posted)
    with session_scope() as session:  # EU group untouched
        assert all(session.get(StoryRow, i).status == "approved" for i in eu)


async def test_group_posts_one_ticker_at_a_time(monkeypatch):
    _fake_publish(monkeypatch)
    first = _candidate_group("AAPL", "US")   # lower ids → posted first
    _candidate_group("MSFT", "US")
    posted = await publish_next_candidate_group(market="US")
    assert set(posted) == set(first)


async def test_group_dedupes_to_one_per_part(monkeypatch):
    _fake_publish(monkeypatch)
    old = _candidate_group("JPM", "US")          # first (stale) set
    new = _candidate_group("JPM", "US")          # rebuilt set, higher ids
    posted = await publish_next_candidate_group(market="US")
    assert len(posted) == 3                        # one chart + one fundamental + one overall
    assert set(posted) == set(new)                 # newest per part wins
    with session_scope() as session:              # old duplicates were not posted
        assert all(session.get(StoryRow, i).status == "approved" for i in old)


async def test_group_stale_day_not_posted(monkeypatch):
    _fake_publish(monkeypatch)
    _candidate_group("JPM", "US", status="approved")
    # override trade_date to an old day via a fresh group
    with session_scope() as session:
        for r in session.query(StoryRow).all():
            r.trade_date = "2000-01-01"
    assert await publish_next_candidate_group(market="US") == []


async def test_publish_story_requires_config():
    import pytest
    with pytest.raises(instagram.PublishError):
        await instagram.publish_story("card.jpg")
