"""Story posting queue (publish_next_story) — publish_story is faked, no network."""
from src.publish import instagram
from src.stocks.pipeline import publish_next_story
from src.storage.database import StoryRow, session_scope


def _make_story(kind: str, market: str = "", status: str = "approved") -> int:
    with session_scope() as session:
        row = StoryRow(kind=kind, market=market, image_path="card.jpg",
                       status=status, trade_date="2026-07-20")
        session.add(row)
        session.flush()
        return row.id


def _fake_publish(monkeypatch, media_id: str = "IG_MEDIA_1"):
    async def _pub(_image_path: str) -> str:
        return media_id
    monkeypatch.setattr(instagram, "publish_story", _pub)


async def test_publish_next_story_marks_published(monkeypatch):
    _fake_publish(monkeypatch)
    sid = _make_story("earnings")
    assert await publish_next_story(kinds=["earnings"]) == sid
    with session_scope() as session:
        row = session.get(StoryRow, sid)
        assert row.status == "published"
        assert row.ig_media_id == "IG_MEDIA_1"


async def test_market_filter_only_posts_matching_market(monkeypatch):
    _fake_publish(monkeypatch)
    eu = _make_story("candidate", "EU")
    us = _make_story("candidate", "US")
    assert await publish_next_story(kinds=["candidate"], market="US") == us
    with session_scope() as session:
        assert session.get(StoryRow, eu).status == "approved"  # EU untouched


async def test_oldest_first(monkeypatch):
    _fake_publish(monkeypatch)
    first = _make_story("candidate", "EU")
    _make_story("candidate", "EU")
    assert await publish_next_story(kinds=["candidate"], market="EU") == first


async def test_returns_none_when_nothing_approved(monkeypatch):
    _fake_publish(monkeypatch)
    _make_story("earnings", status="pending_review")  # not approved
    assert await publish_next_story(kinds=["earnings"]) is None


async def test_failure_marks_story_failed(monkeypatch):
    async def _boom(_image_path: str) -> str:
        raise instagram.PublishError("kaputt")
    monkeypatch.setattr(instagram, "publish_story", _boom)
    sid = _make_story("earnings")
    assert await publish_next_story(kinds=["earnings"]) is None
    with session_scope() as session:
        assert session.get(StoryRow, sid).status == "failed"


async def test_publish_story_requires_config():
    # PUBLIC_MEDIA_* are unset in tests → raises before any network call.
    import pytest
    with pytest.raises(instagram.PublishError):
        await instagram.publish_story("card.jpg")
