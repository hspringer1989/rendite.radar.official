"""Review queue via Telegram: every rendered reel is sent with inline buttons.
Approval decisions update the reel status; the scheduler only publishes
status='approved'. (Same notification channel pattern as trading-bot.)"""
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config
from src.storage.database import ReelRow, StoryRow, session_scope

_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zum nächsten Slot gepostet"),
    "reject": ("rejected", "❌ Verworfen"),
    "regen": ("regenerate", "🔄 Wird neu generiert"),
}

_STORY_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zur passenden Handelszeit gepostet"),
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
        if story.kind == "candidate" and story.ticker:
            rows = session.execute(
                select(StoryRow).where(
                    StoryRow.kind == "candidate",
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


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        if query.data.startswith("story:"):
            _, action, raw_id = query.data.split(":", 2)
            ack = apply_story_decision(int(raw_id), action)
        else:
            action, raw_id = query.data.split(":", 1)
            ack = apply_decision(int(raw_id), action)
    except (ValueError, AttributeError):
        ack = None
    caption = query.message.caption or ""
    await query.edit_message_caption(
        caption=f"{caption}\n\n{ack or '⚠️ Unbekannte Aktion'}"[:1024], reply_markup=None
    )


def build_application() -> Application:
    """Polling application for `python main.py run` — processes review buttons."""
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(_on_callback))
    return app
