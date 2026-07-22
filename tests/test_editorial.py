"""Weekly editorial workflow: slot computation, topic proposal, batch scheduling."""
from datetime import datetime

import pytest

from src.content.llm import builtin_fake
from src.feedposts import editorial
from src.storage.database import FeedPostRow, session_scope


def test_next_week_slots_are_next_monday_onwards():
    slots = editorial.next_week_slots("17:00", 7)
    assert len(slots) == 7
    first = datetime.strptime(slots[0], "%Y-%m-%d %H:%M")
    assert first.weekday() == 0                     # starts on a Monday
    assert first.date() > datetime.now().date()     # strictly in the future
    assert all(s.endswith("17:00") for s in slots)
    days = [datetime.strptime(s, "%Y-%m-%d %H:%M").date() for s in slots]
    assert (days[-1] - days[0]).days == 6           # 7 consecutive days


def test_propose_week_topics():
    topics = editorial.propose_week_topics(builtin_fake(), 7)
    assert len(topics) == 7
    assert all(t["title"] and t["brief"] and t["slug"] for t in topics)


def test_schedule_week_creates_scheduled_review_posts(monkeypatch):
    pytest.importorskip("PIL")

    async def _noop(_pid):
        return None
    monkeypatch.setattr(editorial, "send_feed_for_review", _noop)

    topics = editorial.propose_week_topics(builtin_fake(), 3)
    ids = editorial.schedule_week(topics, builtin_fake())
    assert len(ids) == 3
    with session_scope() as session:
        for i in ids:
            row = session.get(FeedPostRow, i)
            assert row.status == "pending_review"
            assert row.scheduled_at                  # each got a slot
