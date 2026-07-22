"""Feed-post pipeline: pick next queued topic → generate → render slides → persist
pending_review → Telegram review; and publish approved posts as a carousel."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dataclasses import asdict

from loguru import logger
from sqlalchemy import select

import config
from src.content.llm import LLMProvider, get_llm
from src.feedposts.generator import build_feed_post
from src.feedposts.renderer import render_feed_slides
from src.storage.database import FeedPostRow, FeedTopicRow, session_scope


def _stamp() -> str:
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M%S")


def _full_caption(caption: str, hashtags: list[str]) -> str:
    tags = " ".join(hashtags)
    return f"{caption}\n\n{tags}".strip()


def build_next_feed_post(llm: LLMProvider | None = None) -> int | None:
    """Generate + render the next queued feed topic, persist it pending_review."""
    llm = llm or get_llm()
    with session_scope() as session:
        topic = session.execute(
            select(FeedTopicRow).where(FeedTopicRow.status == "queued")
            .order_by(FeedTopicRow.position)
        ).scalars().first()
        topic_data = (topic.slug, topic.title, topic.brief) if topic else None
    if topic_data is None:
        logger.info("Keine offenen Feed-Themen in der Queue")
        return None

    slug, title, brief = topic_data
    post = build_feed_post(slug, title, brief, llm)
    if post is None:
        logger.warning(f"Feed-Post für Thema '{slug}' konnte nicht generiert werden")
        return None

    image_paths = render_feed_slides(post, str(config.FEED_DIR), _stamp())
    caption = _full_caption(post.caption, post.hashtags)
    with session_scope() as session:
        row = FeedPostRow(
            topic_slug=slug, title=post.title,
            slides_json=json.dumps([asdict(s) for s in post.slides], ensure_ascii=False),
            image_paths_json=json.dumps(image_paths, ensure_ascii=False),
            caption=caption, status="pending_review",
        )
        session.add(row)
        session.flush()
        post_id = row.id
        topic = session.execute(
            select(FeedTopicRow).where(FeedTopicRow.slug == slug)
        ).scalars().first()
        if topic:
            topic.status = "used"
    logger.info(f"Feed-Post #{post_id} ('{slug}', {len(image_paths)} Slides) erstellt")
    return post_id


async def send_feed_for_review(post_id: int) -> None:
    """Send the slides as context photos + one caption message with ✅/❌ buttons."""
    from src.review.telegram_bot import (
        review_configured,
        send_feed_review_prompt,
        send_photo_plain,
    )

    if not review_configured():
        logger.info("Telegram nicht konfiguriert — Feed-Post bleibt in der DB (pending_review)")
        return
    with session_scope() as session:
        row = session.get(FeedPostRow, post_id)
        data = (json.loads(row.image_paths_json), row.title, row.caption) if row else None
    if data is None:
        return
    image_paths, title, caption = data
    for path in image_paths:
        await send_photo_plain(path, f"🖼 {title}")
    await send_feed_review_prompt(post_id, title, caption)


async def announce_new_feed_post(post_id: int, title: str) -> str | None:
    """Auto-post a striking 'NEUER BEITRAG' story after a feed carousel goes live.
    Best-effort: an announcement failure never affects the feed post itself."""
    if not config.FEED_ANNOUNCE_STORY:
        return None
    from src.publish.instagram import publish_story, publishing_configured
    from src.stocks.story_cards import render_new_post_story
    from src.storage.database import StoryRow

    if not publishing_configured():
        return None
    day = datetime.now(ZoneInfo(config.TIMEZONE))
    path = render_new_post_story(title, str(config.STORY_DIR / f"announce_{post_id}_{_stamp()}.jpg"))
    try:
        media_id = await publish_story(path)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"New-Post-Story fehlgeschlagen: {exc}")
        return None
    with session_scope() as session:
        session.add(StoryRow(
            kind="announce", trade_date=day.strftime("%Y-%m-%d"), image_path=path,
            caption=f"Neuer Beitrag: {title}", status="published", ig_media_id=media_id,
            published_at=datetime.now(timezone.utc).isoformat(),
        ))
    logger.info(f"New-Post-Story gepostet (IG media id {media_id})")
    return media_id


async def publish_feed_post_by_id(post_id: int) -> int | None:
    """Publish a specific feed post as a carousel, then auto-announce it via a story.
    Records failure, doesn't raise."""
    from src.publish.instagram import publish_feed_post

    with session_scope() as session:
        row = session.get(FeedPostRow, post_id)
        data = (json.loads(row.image_paths_json), row.caption, row.title) if row else None
    if data is None:
        return None
    image_paths, caption, title = data

    try:
        media_id = await publish_feed_post(image_paths, caption)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Feed-Post #{post_id} posten fehlgeschlagen: {exc}")
        with session_scope() as session:
            r = session.get(FeedPostRow, post_id)
            r.status = "failed"
            r.error = str(exc)[:2000]
        return None

    with session_scope() as session:
        r = session.get(FeedPostRow, post_id)
        r.status = "published"
        r.ig_media_id = media_id
        r.published_at = datetime.now(timezone.utc).isoformat()
    logger.info(f"Feed-Post #{post_id} veröffentlicht (IG media id {media_id})")
    await announce_new_feed_post(post_id, title)
    return post_id


async def publish_next_feed_post(trade_date: str | None = None) -> int | None:
    """Publish the oldest approved UNSCHEDULED feed post (+ its announcement story).
    Time-scheduled posts (scheduled_at set) are handled separately by the scheduler."""
    with session_scope() as session:
        row = session.execute(
            select(FeedPostRow).where(
                FeedPostRow.status == "approved", FeedPostRow.scheduled_at == ""
            ).order_by(FeedPostRow.id)
        ).scalars().first()
        pid = row.id if row else None
    return await publish_feed_post_by_id(pid) if pid is not None else None


async def publish_due_scheduled_feed_posts(now_local: str) -> list[int]:
    """Publish approved feed posts whose scheduled_at has arrived (now_local as
    'YYYY-MM-DD HH:MM'). Returns the posted ids."""
    with session_scope() as session:
        due = session.execute(
            select(FeedPostRow.id).where(
                FeedPostRow.status == "approved",
                FeedPostRow.scheduled_at != "",
                FeedPostRow.scheduled_at <= now_local,
            ).order_by(FeedPostRow.scheduled_at)
        ).scalars().all()
    posted: list[int] = []
    for pid in due:
        if await publish_feed_post_by_id(pid) is not None:
            posted.append(pid)
    return posted
