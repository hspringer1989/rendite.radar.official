"""Daily stock-story pipeline: today's earnings card + 3–4 sector-diversified
watchlist candidate cards → persisted as StoryRow(pending_review) → Telegram preview.

This first slice stops at the review queue: nothing is auto-posted to Instagram
yet (that is the next slice, incl. US/EU time-zone slots)."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone as _tz
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

import config
from src.content.llm import LLMProvider, get_llm
from src.models import Candidate
from src.stocks.analyzer import build_candidates
from src.stocks.market_data import MarketData, get_earnings_calendar, get_market_data
from src.stocks.story_cards import (
    render_candidates_overview_card,
    render_chart_card,
    render_earnings_card,
    render_fundamental_card,
    render_overall_card,
)
from src.storage.database import StoryRow, session_scope

_DISCLAIMER = "⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung. Werbung."


def _today_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _stamp() -> str:
    return _today_local().strftime("%Y%m%d_%H%M%S")


def _recent_candidate_tickers(cooldown_days: int) -> set[str]:
    """Tickers analysed as candidates within the cooldown window — held back from a new
    build so the same stock is not re-analysed within `cooldown_days`. `superseded`/
    `failed` cards don't count (they never reached the audience)."""
    cutoff = (_today_local() - timedelta(days=cooldown_days)).strftime("%Y-%m-%d")
    with session_scope() as session:
        rows = session.execute(
            select(StoryRow.ticker).where(
                StoryRow.kind.in_(("candidate", "trend")),   # both categories share the cooldown
                StoryRow.ticker != "",
                StoryRow.trade_date >= cutoff,
                StoryRow.status.in_(("pending_review", "approved", "published", "rejected")),
            )
        ).scalars().all()
    return {t for t in rows}


def _persist(kind: str, image_path: str, caption: str, trade_date: str,
             ticker: str = "", market: str = "", part: str = "",
             analysis: dict | None = None) -> int:
    with session_scope() as session:
        row = StoryRow(
            kind=kind, part=part, ticker=ticker, market=market, image_path=image_path,
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

    # 2) Watchlist candidates (chart + fundamentals, no sentiment) — respecting the
    #    per-ticker cooldown so recently-analysed stocks are not repeated.
    exclude = _recent_candidate_tickers(config.STOCK_REPEAT_COOLDOWN_DAYS)
    if exclude:
        logger.info(f"Cooldown: {len(exclude)} Ticker der letzten "
                    f"{config.STOCK_REPEAT_COOLDOWN_DAYS} Tage ausgeschlossen")
    candidates = build_candidates(md, config.STOCK_UNIVERSE, llm, exclude=exclude)
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

    # 3) Three cards per candidate (Charttechnik → Fundamental → Gesamtbild),
    #    posted as a group later at the market's trading hours.
    for c in candidates:
        story_ids.extend(_persist_candidate_cards(c, out_dir, trade_date))

    # 4) News-driven "Trend-Aktie": one stock most in the news today (same cooldown
    #    pool, so it never repeats a recently-shown ticker), analysed the same way.
    if config.STOCK_TREND_ENABLED:
        story_ids.extend(_build_trend_story(md, llm, out_dir, trade_date, exclude))

    logger.info(f"{len(story_ids)} Story-Cards erstellt (pending_review)")
    return story_ids


def _build_trend_story(md, llm, out_dir: Path, trade_date: str, exclude: set[str]) -> list[int]:
    """Pick the day's news-trending stock (not in the cooldown set) and render its
    3-card 'Trend-Aktie' story. Returns the created ids (empty if none found)."""
    from src.stocks.analyzer import build_candidate_for_ticker
    from src.stocks.news_trend import select_trend_ticker

    pick = select_trend_ticker(md, llm, exclude)
    if pick is None:
        logger.info("Keine Trend-Aktie heute")
        return []
    ticker, _name, reason = pick
    candidate = build_candidate_for_ticker(md, ticker, llm, category="TREND-AKTIE",
                                           trend_reason=reason)
    if candidate is None:
        logger.warning(f"Trend-Aktie {ticker} konnte nicht analysiert werden")
        return []
    ids = _persist_candidate_cards(candidate, out_dir, trade_date, kind="trend")
    logger.info(f"Trend-Aktien-Story erstellt: {ticker}")
    return ids


def _persist_candidate_cards(
    c: Candidate, out_dir: Path, trade_date: str, kind: str = "candidate",
) -> list[int]:
    """Render + persist the 3 cards (chart, fundamental, overall) for one candidate/trend
    stock. Supersedes any earlier same-day cards for this ticker+kind so a re-build never
    stacks duplicate frames onto the same story."""
    m = c.metrics
    with session_scope() as session:
        prior = session.execute(
            select(StoryRow).where(
                StoryRow.kind == kind, StoryRow.ticker == m.ticker,
                StoryRow.trade_date == trade_date,
                StoryRow.status.in_(("pending_review", "approved")),
            )
        ).scalars().all()
        for row in prior:
            row.status = "superseded"
        if prior:
            logger.info(f"{m.ticker} ({kind}): {len(prior)} ältere Card(s) verworfen")

    stamp = _stamp()
    lead = "🔥 Trend-Aktie" if kind == "trend" else f"{m.ticker} · {m.sector}"
    parts = [
        ("chart", render_chart_card, "Charttechnik"),
        ("fundamental", render_fundamental_card, "Fundamental"),
        ("overall", render_overall_card, "Gesamtbild"),
    ]
    ids: list[int] = []
    for part, render, label in parts:
        path = render(c, str(out_dir / f"{kind}_{m.ticker}_{part}_{stamp}.jpg"))
        caption = f"{lead} — {m.ticker} · {label}\n\n{_DISCLAIMER}"
        ids.append(_persist(kind, path, caption, trade_date,
                            ticker=m.ticker, market=m.market, part=part,
                            analysis=asdict(c) if part == "overall" else None))
    return ids


async def _publish_one(story_id: int) -> int | None:
    """Publish a single StoryRow by id; record failure instead of raising."""
    from src.publish.instagram import publish_story

    with session_scope() as session:
        story = session.get(StoryRow, story_id)
        if story is None:
            return None
        image_path, kind, market = story.image_path, story.kind, story.market
    try:
        media_id = await publish_story(image_path)
    except Exception as exc:  # noqa: BLE001 — record the failure, keep the loop alive
        logger.error(f"Story #{story_id} posten fehlgeschlagen: {exc}")
        with session_scope() as session:
            row = session.get(StoryRow, story_id)
            row.status = "failed"
            row.error = str(exc)[:2000]
        return None

    with session_scope() as session:
        row = session.get(StoryRow, story_id)
        row.status = "published"
        row.ig_media_id = media_id
        row.published_at = datetime.now(_tz.utc).isoformat()
    logger.info(f"Story #{story_id} ({kind}/{market or '—'}) veröffentlicht")
    return story_id


async def publish_next_story(
    kinds: list[str] | None = None,
    market: str | None = None,
    trade_date: str | None = None,
) -> int | None:
    """Publish the oldest approved single story (earnings / overview) for `trade_date`
    (defaults to today) — so a leftover from a previous day is never posted stale."""
    trade_date = trade_date or _today_local().strftime("%Y-%m-%d")
    with session_scope() as session:
        query = select(StoryRow.id).where(
            StoryRow.status == "approved", StoryRow.trade_date == trade_date
        )
        if kinds:
            query = query.where(StoryRow.kind.in_(kinds))
        if market:
            query = query.where(StoryRow.market == market)
        sid = session.execute(query.order_by(StoryRow.id)).scalars().first()
    return await _publish_one(sid) if sid is not None else None


_PART_ORDER = {"chart": 0, "fundamental": 1, "overall": 2}


async def publish_next_candidate_group(
    market: str | None = None, trade_date: str | None = None, kind: str = "candidate",
) -> list[int]:
    """Publish all approved cards of the NEXT candidate/trend ticker (chart → fundamental
    → overall) for today+market as a story sequence. Returns the posted ids."""
    trade_date = trade_date or _today_local().strftime("%Y-%m-%d")
    with session_scope() as session:
        query = select(StoryRow).where(
            StoryRow.status == "approved", StoryRow.trade_date == trade_date,
            StoryRow.kind == kind,
        )
        if market:
            query = query.where(StoryRow.market == market)
        rows = [(r.id, r.ticker, r.part)
                for r in session.execute(query.order_by(StoryRow.id)).scalars().all()]
    if not rows:
        return []

    ticker = rows[0][1]
    # dedupe safety: at most ONE card per part (newest id wins), ordered chart→…→overall
    newest: dict[str, int] = {}
    for sid, tk, part in sorted((r for r in rows if r[1] == ticker), key=lambda r: r[0]):
        newest[part] = sid
    ordered = sorted(newest.items(), key=lambda kv: _PART_ORDER.get(kv[0], 9))

    posted: list[int] = []
    for _part, sid in ordered:
        pid = await _publish_one(sid)
        if pid is not None:
            posted.append(pid)
    return posted


async def send_stories_for_review(story_ids: list[int]) -> None:
    """Push the freshly rendered story cards to the Telegram review queue. For a
    candidate, the chart+fundamental frames are sent as context (no buttons); the
    overall frame carries the ✅/❌ that approves the whole ticker group."""
    from src.review.telegram_bot import (
        review_configured,
        send_photo_for_review,
        send_photo_plain,
    )

    if not review_configured():
        logger.info("Telegram nicht konfiguriert — Stories bleiben in der DB (pending_review)")
        return
    for sid in story_ids:
        with session_scope() as session:
            story = session.get(StoryRow, sid)
            data = (story.kind, story.part, story.image_path, story.caption) if story else None
        if data is None:
            continue
        kind, part, image_path, caption = data
        if kind in ("candidate", "trend") and part in ("chart", "fundamental"):
            await send_photo_plain(image_path, caption)
        else:
            await send_photo_for_review(sid, image_path, caption)
