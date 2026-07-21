"""Feed-post generation, review, publishing. Rendering is skipped without Pillow."""
import json

import pytest
from sqlalchemy import select

from src.content.llm import FakeLLM, builtin_fake
from src.feedposts.generator import build_feed_post
from src.publish import instagram
from src.review.telegram_bot import apply_feed_decision
from src.storage.database import FeedPostRow, FeedTopicRow, session_scope


# ── generator ──────────────────────────────────────────────────────────────
def test_build_feed_post_returns_slides_with_disclaimer():
    post = build_feed_post("strategie-auswahl", "Titel", "brief", builtin_fake())
    assert post is not None
    assert len(post.slides) >= 3
    assert "anlageberatung" in post.caption.lower()
    assert post.hashtags


def test_generator_sanitises_banned_phrase():
    llm = FakeLLM({"feed_post": json.dumps({
        "title": "t",
        "slides": [
            {"heading": "h", "body": "Kaufen Sie jetzt diese Aktie."},
            {"heading": "h2", "body": "Zweiter Slide mit Inhalt."},
            {"heading": "h3", "body": "Dritter Slide, Call-to-Action."},
        ],
        "caption": "c", "hashtags": ["#x"],
    })})
    post = build_feed_post("s", "t", "b", llm)
    assert "kaufen sie" not in post.slides[0].body.lower()


def test_generator_rejects_too_few_slides():
    llm = FakeLLM({"feed_post": json.dumps({
        "title": "t", "slides": [{"heading": "h", "body": "nur einer"}],
        "caption": "c", "hashtags": [],
    })})
    assert build_feed_post("s", "t", "b", llm) is None


# ── pipeline (needs Pillow for rendering) ──────────────────────────────────
def test_build_next_feed_post_creates_row_and_uses_topic():
    pytest.importorskip("PIL")
    from src.feedposts.pipeline import build_next_feed_post

    pid = build_next_feed_post(builtin_fake())
    assert pid is not None
    with session_scope() as session:
        row = session.get(FeedPostRow, pid)
        assert row.status == "pending_review"
        slug = row.topic_slug
        paths = json.loads(row.image_paths_json)
        assert len(paths) >= 3 and all(p.endswith(".jpg") for p in paths)
        topic = session.execute(
            select(FeedTopicRow).where(FeedTopicRow.slug == slug)
        ).scalars().first()
        assert topic.status == "used"


# ── review decision ────────────────────────────────────────────────────────
def _make_post(status: str = "pending_review", paths=None) -> int:
    with session_scope() as session:
        row = FeedPostRow(status=status,
                          image_paths_json=json.dumps(paths or ["a.jpg", "b.jpg"]),
                          caption="Caption")
        session.add(row)
        session.flush()
        return row.id


def test_feed_decision_approve_and_double():
    pid = _make_post()
    assert apply_feed_decision(pid, "approve")
    with session_scope() as session:
        assert session.get(FeedPostRow, pid).status == "approved"
    assert "bereits" in apply_feed_decision(pid, "reject")


# ── publishing (faked, no network) ─────────────────────────────────────────
async def test_publish_next_feed_post_marks_published(monkeypatch):
    async def _fake(_paths, _caption):
        return "IG_FEED_1"
    monkeypatch.setattr(instagram, "publish_feed_post", _fake)
    from src.feedposts.pipeline import publish_next_feed_post

    pid = _make_post(status="approved")
    assert await publish_next_feed_post() == pid
    with session_scope() as session:
        row = session.get(FeedPostRow, pid)
        assert row.status == "published"
        assert row.ig_media_id == "IG_FEED_1"


async def test_publish_feed_requires_config():
    with pytest.raises(instagram.PublishError):
        await instagram.publish_feed_post(["a.jpg"], "caption")
