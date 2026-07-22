"""Weekly editorial workflow: plan + create the coming week's feed posts together, then
publish them at one fixed daily slot (Mon–Sun). The Sunday reminder proposes topics; a
session then generates the agreed posts, each scheduled to its day, for batch approval."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

import config
from src.content.llm import LLMProvider, get_llm, parse_json_response
from src.content.usage import claude_budget_exceeded
from src.feedposts.generator import build_feed_post
from src.feedposts.pipeline import _full_caption, _stamp, send_feed_for_review
from src.feedposts.renderer import render_feed_slides
from src.storage.database import FeedPostRow, session_scope
from sqlalchemy import select


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def next_week_slots(post_time: str | None = None, days: int | None = None) -> list[str]:
    """The coming Mon..(Mon+days-1) at `post_time`, as 'YYYY-MM-DD HH:MM' local strings.
    Always the NEXT Monday strictly in the future."""
    post_time = post_time or config.FEED_DAILY_POST_TIME
    days = days or config.FEED_WEEKLY_POSTS
    today = _now()
    ahead = (0 - today.weekday()) % 7 or 7          # days until next Monday (never today)
    monday = (today + timedelta(days=ahead)).date()
    return [f"{monday + timedelta(days=i)} {post_time}" for i in range(days)]


def recent_titles(limit: int = 40) -> list[str]:
    with session_scope() as session:
        return [t for (t,) in session.execute(
            select(FeedPostRow.title).order_by(FeedPostRow.id.desc()).limit(limit)
        ).all() if t]


_PROPOSE_SYSTEM = """Du bist Redakteur für das deutsche Instagram-Finanz-Bildungsprofil \
"Renditeradar" (datenbasiert, Ampel aus Charttechnik + Fundamental; Zielgruppe: FORTGESCHRITTENE \
Privatanleger, kein Anfänger-Basic). Schlage reichweitenstarke Beitragsthemen vor — \
abwechslungsreiche Formate (Erklär-Carousel, Listen/Rankings, Mythen-Check, anwendbare How-tos, \
Strategie), fortgeschrittener Ton, immer mit Anwendbarkeit/Entscheidungslogik.
Verwende korrekte deutsche Umlaute. Antworte AUSSCHLIESSLICH mit gültigem JSON."""

_PROPOSE_USER = """Schlage {n} Beitragsthemen für die kommende Woche vor (ein Beitrag pro Tag).
Vermeide diese kürzlich behandelten Themen: {avoid}

Gib genau diese JSON-Struktur zurück:
{{"topics": [
  {{"slug": "kurz-kebab-case", "title": "knackiger Titel", "brief": "1-2 Sätze: worum es geht, welche Entscheidungslogik/Anwendbarkeit"}}
]}}"""


def propose_week_topics(llm: LLMProvider | None = None, n: int | None = None) -> list[dict]:
    """One budget-gated Claude call → a list of {slug, title, brief} topic proposals."""
    n = n or config.FEED_WEEKLY_POSTS
    llm = llm or get_llm()
    if claude_budget_exceeded():
        return []
    try:
        raw = llm.complete(
            system=_PROPOSE_SYSTEM,
            user=_PROPOSE_USER.format(n=n, avoid="; ".join(recent_titles()) or "—"),
            model=config.CLAUDE_MODEL_FAST, max_tokens=1200, purpose="week_plan",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Themenvorschlag fehlgeschlagen: {exc}")
        return []
    data = parse_json_response(raw)
    topics = data.get("topics", []) if isinstance(data, dict) else []
    out = []
    for t in topics[:n]:
        if isinstance(t, dict) and t.get("title") and t.get("brief"):
            out.append({
                "slug": str(t.get("slug") or t["title"]).strip().lower().replace(" ", "-")[:60],
                "title": str(t["title"]).strip(),
                "brief": str(t["brief"]).strip(),
            })
    return out


def schedule_week(topics: list[dict], llm: LLMProvider | None = None) -> list[int]:
    """Generate the agreed topics, assign each to the next week's daily slots, and send
    them to the Telegram review queue (they publish at their slot after approval).
    `topics`: list of {slug, title, brief}. Returns the created post ids."""
    import asyncio

    llm = llm or get_llm()
    slots = next_week_slots()
    created: list[int] = []
    for topic, slot in zip(topics, slots):
        post = build_feed_post(topic["slug"], topic["title"], topic["brief"], llm)
        if post is None:
            logger.warning(f"Thema '{topic['slug']}' konnte nicht generiert werden")
            continue
        paths = render_feed_slides(post, str(config.FEED_DIR), _stamp())
        with session_scope() as session:
            row = FeedPostRow(
                topic_slug=topic["slug"], title=post.title,
                slides_json=json.dumps([asdict(s) for s in post.slides], ensure_ascii=False),
                image_paths_json=json.dumps(paths, ensure_ascii=False),
                caption=_full_caption(post.caption, post.hashtags),
                status="pending_review", scheduled_at=slot,
            )
            session.add(row)
            session.flush()
            pid = row.id
        created.append(pid)
        logger.info(f"Wochen-Post #{pid} '{topic['slug']}' geplant fuer {slot}")

    async def _send() -> None:
        for pid in created:
            await send_feed_for_review(pid)
    asyncio.run(_send())
    return created


async def send_editorial_reminder() -> None:
    """Sunday: send a Telegram reminder + an auto-drafted topic proposal for next week."""
    from src.review.telegram_bot import review_configured, send_text

    if not review_configured():
        return
    topics = propose_week_topics()
    slots = next_week_slots()
    lines = ["🗓️ Redaktionssitzung — Plan für die kommende Woche",
             f"({len(slots)} Beiträge, je {config.FEED_DAILY_POST_TIME} Uhr, Mo–So)\n"]
    if topics:
        lines.append("Themenvorschlag:")
        for i, t in enumerate(topics):
            day = slots[i][:10] if i < len(slots) else ""
            lines.append(f"{i + 1}. {t['title']}  ({day})")
        lines.append("\nPasst das? Sag mir Änderungen — dann erstelle ich alle Beiträge geplant zur Freigabe.")
    else:
        lines.append("Womit wollen wir die Woche füllen? Nenn mir die Themen.")
    await send_text("\n".join(lines))
    logger.info("Redaktions-Reminder an Telegram gesendet")
