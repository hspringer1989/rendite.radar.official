"""Review queue via Telegram: every rendered reel is sent with inline buttons.
Approval decisions update the reel status; the scheduler only publishes
status='approved'. (Same notification channel pattern as trading-bot.)"""
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config
from src.storage.database import FeedPostRow, ReelRow, StoryRow, session_scope

_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zum nächsten Slot gepostet"),
    "reject": ("rejected", "❌ Verworfen"),
    "regen": ("regenerate", "🔄 Wird neu generiert"),
}

_STORY_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zur passenden Handelszeit gepostet"),
    "reject": ("rejected", "❌ Verworfen"),
}

_FEED_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zum nächsten Feed-Slot gepostet"),
    "reject": ("rejected", "❌ Verworfen"),
}


def review_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _keyboard(reel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Posten", callback_data=f"approve:{reel_id}"),
        InlineKeyboardButton("🔄 Neu", callback_data=f"regen:{reel_id}"),
        InlineKeyboardButton("❌ Verwerfen", callback_data=f"reject:{reel_id}"),
    ]])


def _story_keyboard(story_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Posten", callback_data=f"story:approve:{story_id}"),
        InlineKeyboardButton("❌ Verwerfen", callback_data=f"story:reject:{story_id}"),
    ]])


async def send_for_review(reel_id: int, video_path: str, caption: str) -> None:
    """One-shot send (usable from the CLI without the polling loop running;
    the button callback is processed once `python main.py run` polls)."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"🎬 Reel #{reel_id} wartet auf Freigabe\n\n{caption}"
    async with bot:
        with open(video_path, "rb") as video:
            await bot.send_video(
                chat_id=config.TELEGRAM_CHAT_ID,
                video=video,
                caption=text[:1024],
                reply_markup=_keyboard(reel_id),
                read_timeout=120,
                write_timeout=300,
            )
    logger.info(f"Reel #{reel_id} zur Freigabe an Telegram gesendet")


async def send_photo_for_review(story_id: int, image_path: str, caption: str) -> None:
    """Send a rendered story card as a photo with ✅/❌ review buttons."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"🖼 Story #{story_id} wartet auf Freigabe\n\n{caption}"
    async with bot:
        with open(image_path, "rb") as photo:
            await bot.send_photo(
                chat_id=config.TELEGRAM_CHAT_ID,
                photo=photo,
                caption=text[:1024],
                reply_markup=_story_keyboard(story_id),
                read_timeout=120,
                write_timeout=300,
            )
    logger.info(f"Story #{story_id} zur Freigabe an Telegram gesendet")


def _feed_keyboard(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Posten", callback_data=f"feed:approve:{post_id}"),
        InlineKeyboardButton("❌ Verwerfen", callback_data=f"feed:reject:{post_id}"),
    ]])


async def send_feed_review_prompt(post_id: int, title: str, caption: str) -> None:
    """After the slides, one text message with the caption and ✅/❌ buttons."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = f"📰 Feed-Beitrag #{post_id} wartet auf Freigabe\n\n{title}\n\n{caption}"
    async with bot:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, text=text[:4096],
            reply_markup=_feed_keyboard(post_id),
        )
    logger.info(f"Feed-Post #{post_id} zur Freigabe an Telegram gesendet")


async def send_photo_plain(image_path: str, caption: str) -> None:
    """Send a story card as context (no review buttons) — used for the chart and
    fundamental frames of a candidate; the overall frame carries the approval."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    async with bot:
        with open(image_path, "rb") as photo:
            await bot.send_photo(
                chat_id=config.TELEGRAM_CHAT_ID,
                photo=photo,
                caption=caption[:1024],
                read_timeout=120,
                write_timeout=300,
            )


async def send_text(text: str) -> None:
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=text[:4096])


def apply_decision(reel_id: int, action: str) -> str | None:
    """Pure DB part of a review decision (unit-testable without Telegram)."""
    if action not in _DECISIONS:
        return None
    status, ack = _DECISIONS[action]
    with session_scope() as session:
        reel = session.get(ReelRow, reel_id)
        if reel is None:
            return None
        if reel.status not in ("pending_review", "regenerate"):
            return f"Reel #{reel_id} ist bereits '{reel.status}'"
        reel.status = status
    logger.info(f"Review-Entscheidung für Reel #{reel_id}: {status}")
    return ack


def apply_story_decision(story_id: int, action: str) -> str | None:
    """Pure DB part of a story review decision (unit-testable without Telegram).
    For a candidate the decision cascades to ALL cards of that ticker+date (the 3
    frames are approved/rejected together via the button on the overall frame)."""
    if action not in _STORY_DECISIONS:
        return None
    status, ack = _STORY_DECISIONS[action]
    with session_scope() as session:
        story = session.get(StoryRow, story_id)
        if story is None:
            return None
        if story.status != "pending_review":
            return f"Story #{story_id} ist bereits '{story.status}'"
        if story.kind in ("candidate", "trend") and story.ticker:
            rows = session.execute(
                select(StoryRow).where(
                    StoryRow.kind == story.kind,
                    StoryRow.ticker == story.ticker,
                    StoryRow.trade_date == story.trade_date,
                    StoryRow.status == "pending_review",
                )
            ).scalars().all()
            for row in rows:
                row.status = status
            count = len(rows)
        else:
            story.status = status
            count = 1
    logger.info(f"Review-Entscheidung für Story #{story_id}: {status} ({count} Card(s))")
    return ack


def apply_feed_decision(post_id: int, action: str) -> str | None:
    """Pure DB part of a feed-post review decision (unit-testable without Telegram)."""
    if action not in _FEED_DECISIONS:
        return None
    status, ack = _FEED_DECISIONS[action]
    with session_scope() as session:
        post = session.get(FeedPostRow, post_id)
        if post is None:
            return None
        if post.status != "pending_review":
            return f"Feed-Post #{post_id} ist bereits '{post.status}'"
        post.status = status
    logger.info(f"Review-Entscheidung für Feed-Post #{post_id}: {status}")
    return ack


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    kind, action, item_id, ack = None, None, None, None
    try:
        if query.data.startswith("story:"):
            _, action, raw_id = query.data.split(":", 2)
            kind, item_id = "story", int(raw_id)
            ack = apply_story_decision(item_id, action)
        elif query.data.startswith("feed:"):
            _, action, raw_id = query.data.split(":", 2)
            kind, item_id = "feed", int(raw_id)
            ack = apply_feed_decision(item_id, action)
        else:
            action, raw_id = query.data.split(":", 1)
            kind, item_id = "reel", int(raw_id)
            ack = apply_decision(item_id, action)
    except (ValueError, AttributeError):
        ack = None
    msg = query.message
    note = ack or "⚠️ Unbekannte Aktion"
    if msg.caption is not None:  # photo message (reel/story)
        await query.edit_message_caption(
            caption=f"{msg.caption}\n\n{note}"[:1024], reply_markup=None
        )
    else:  # text message (feed-post review prompt)
        await query.edit_message_text(
            text=f"{msg.text or ''}\n\n{note}"[:4096], reply_markup=None
        )

    # On approval a feed post publishes IMMEDIATELY (+ announcement story) — UNLESS it has
    # a future scheduled_at, in which case the scheduler posts it at that time.
    if kind == "feed" and action == "approve" and ack and "bereits" not in ack:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now_local = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d %H:%M")
        with session_scope() as session:
            post = session.get(FeedPostRow, item_id)
            scheduled = post.scheduled_at if post else ""
        if scheduled and scheduled > now_local:
            await send_text(f"🕒 Feed-Beitrag #{item_id} freigegeben — wird am {scheduled} Uhr gepostet.")
        else:
            from src.feedposts.pipeline import publish_feed_post_by_id

            posted = await publish_feed_post_by_id(item_id)
            await send_text(
                f"📤 Feed-Beitrag #{item_id} wurde gepostet (+ Ankündigungs-Story)."
                if posted else
                f"⚠️ Feed-Beitrag #{item_id} konnte nicht gepostet werden (siehe Logs)."
            )


def build_application() -> Application:
    """Polling application for `python main.py run` — processes review buttons."""
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_on_callback))
    return app
