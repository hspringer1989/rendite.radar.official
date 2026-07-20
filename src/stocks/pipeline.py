"""Daily stock-story pipeline: today's earnings card + 3–4 sector-diversified
watchlist candidate cards → persisted as StoryRow(pending_review) → Telegram preview.

This first slice stops at the review queue: nothing is auto-posted to Instagram
yet (that is the next slice, incl. US/EU time-zone slots)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from datetime import datetime, timezone as _tz

from loguru import logger
from sqlalchemy import select

import config
from src.content.llm import LLMProvider, get_llm
from src.models import Candidate
from src.stocks.analyzer import build_candidates
from src.stocks.market_data import MarketData, get_earnings_calendar, get_market_data
from src.stocks.story_cards import (
    render_candidate_card,
    render_candidates_overview_card,
    render_earnings_card,
)
from src.storage.database import StoryRow, session_scope

_DISCLAIMER = "⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung. Werbung."


def _today_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _stamp() -> str:
    return _today_local().strftime("%Y%m%d_%H%M%S")


def _persist(kind: str, image_path: str, caption: str, trade_date: str,
             ticker: str = "", market: str = "", analysis: dict | None = None) -> int:
    with session_scope() as session:
        row = StoryRow(
            kind=kind, ticker=ticker, market=market, image_path=image_path,
            caption=caption, trade_date=trade_date, status="pending_review",
            analysis_json=json.dumps(analysis, ensure_ascii=False) if analysis else "",
        )
        session.add(row)
        session.flush()
        return row.id


def build_daily_stories(
    md: MarketData | None = None, llm: LLMProvider | None = None
) -> list[int]:
    """Render today's earnings + candidate story cards, persist them pending_review.
    Returns the created StoryRow ids (earnings first, then overview, then candidates)."""
    md = md or get_market_data()
    llm = llm or get_llm()
    day = _today_local()
    trade_date = day.strftime("%Y-%m-%d")
    day_label = day.strftime("%d.%m.%Y")
    out_dir = Path(config.STORY_DIR)
    story_ids: list[int] = []

    # 1) Earnings-of-the-day card
    earnings = get_earnings_calendar().todays(config.STOCK_UNIVERSE, config.TIMEZONE)
    e_path = render_earnings_card(earnings, str(out_dir / f"earnings_{_stamp()}.jpg"), day_label)
    e_caption = f"📅 Quartalszahlen heute ({day_label})\n\n{_DISCLAIMER}"
    story_ids.append(_persist("earnings", e_path, e_caption, trade_date,
                              analysis={"tickers": [e.ticker for e in earnings]}))
    logger.info(f"Earnings-Story erstellt: {len(earnings)} Termine")

    # 2) Watchlist candidates (chart + fundamentals, no sentiment)
    candidates = build_candidates(md, config.STOCK_UNIVERSE, llm)
    if not candidates:
        logger.warning("Keine Kandidaten — nur Earnings-Story erstellt")
        return story_ids

    o_path = render_candidates_overview_card(
        candidates, str(out_dir / f"watchlist_{_stamp()}.jpg")
    )
    o_caption = ("🔎 Meine Watchlist heute — Charttechnik & Fundamental\n\n"
                 f"{_DISCLAIMER}")
    story_ids.append(_persist("candidates", o_path, o_caption, trade_date,
                              analysis={"tickers": [c.metrics.ticker for c in candidates]}))

    # 3) One card per candidate (posted later at its market's trading hours)
    for c in candidates:
        story_ids.append(_persist_candidate(c, out_dir, trade_date))

    logger.info(f"{len(story_ids)} Story-Cards erstellt (pending_review)")
    return story_ids


def _persist_candidate(c: Candidate, out_dir: Path, trade_date: str) -> int:
    m = c.metrics
    path = render_candidate_card(c, str(out_dir / f"cand_{m.ticker}_{_stamp()}.jpg"))
    caption = (f"{m.ticker} · {m.sector} — was Chart & Fundamentaldaten zeigen\n\n{_DISCLAIMER}")
    return _persist("candidate", path, caption, trade_date,
                    ticker=m.ticker, market=m.market, analysis=asdict(c))


async def publish_next_story(
    kinds: list[str] | None = None, market: str | None = None
) -> int | None:
    """Publish the oldest approved story matching the filters (kind / market).
    Returns its id, or None if nothing matches. Failures are recorded, not raised."""
    from src.publish.instagram import publish_story

    with session_scope() as session:
        query = select(StoryRow).where(StoryRow.status == "approved")
        if kinds:
            query = query.where(StoryRow.kind.in_(kinds))
        if market:
            query = query.where(StoryRow.market == market)
        story = session.execute(query.order_by(StoryRow.id)).scalars().first()
    if story is None:
        return None

    try:
        media_id = await publish_story(story.image_path)
    except Exception as exc:  # noqa: BLE001 — record the failure, keep the loop alive
        logger.error(f"Story #{story.id} posten fehlgeschlagen: {exc}")
        with session_scope() as session:
            row = session.get(StoryRow, story.id)
            row.status = "failed"
            row.error = str(exc)[:2000]
        return None

    with session_scope() as session:
        row = session.get(StoryRow, story.id)
        row.status = "published"
        row.ig_media_id = media_id
        row.published_at = datetime.now(_tz.utc).isoformat()
    logger.info(f"Story #{story.id} ({story.kind}/{story.market or '—'}) veröffentlicht")
    return story.id


async def send_stories_for_review(story_ids: list[int]) -> None:
    """Push the freshly rendered story cards to the Telegram review queue."""
    from src.review.telegram_bot import review_configured, send_photo_for_review

    if not review_configured():
        logger.info("Telegram nicht konfiguriert — Stories bleiben in der DB (pending_review)")
        return
    for sid in story_ids:
        with session_scope() as session:
            story = session.get(StoryRow, sid)
        if story:
            await send_photo_for_review(sid, story.image_path, story.caption)
