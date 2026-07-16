"""Review queue via Telegram: every rendered reel is sent with inline buttons.
Approval decisions update the reel status; the scheduler only publishes
status='approved'. (Same notification channel pattern as trading-bot.)"""
from pathlib import Path

from loguru import logger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config
from src.storage.database import ReelRow, session_scope

_DECISIONS = {
    "approve": ("approved", "✅ Freigegeben — wird zum nächsten Slot gepostet"),
    "reject": ("rejected", "❌ Verworfen"),
    "regen": ("regenerate", "🔄 Wird neu generiert"),
}


def review_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _keyboard(reel_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Posten", callback_data=f"approve:{reel_id}"),
        InlineKeyboardButton("🔄 Neu", callback_data=f"regen:{reel_id}"),
        InlineKeyboardButton("❌ Verwerfen", callback_data=f"reject:{reel_id}"),
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


async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
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
