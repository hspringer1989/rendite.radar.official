"""Hard daily budget gates for paid APIs (simplified from trading-bot's
src/analysis/usage.py). No automatic call ever exceeds the daily cap."""
from datetime import datetime, timezone

from loguru import logger

import config
from src.storage.database import ApiUsageRow, daily_usage_eur, daily_usage_units, session_scope

# EUR per 1M tokens (input, output) — rough pricing for budget gating, not billing
_MODEL_PRICES_EUR = {
    "haiku": (0.9, 4.5),
    "sonnet": (2.8, 14.0),
    "opus": (14.0, 70.0),
}


def _price_for(model: str) -> tuple[float, float]:
    for key, price in _MODEL_PRICES_EUR.items():
        if key in model:
            return price
    return _MODEL_PRICES_EUR["sonnet"]  # unknown model: assume mid-tier


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record_claude(model: str, input_tokens: int, output_tokens: int, purpose: str) -> None:
    p_in, p_out = _price_for(model)
    cost = (input_tokens * p_in + output_tokens * p_out) / 1_000_000
    with session_scope() as session:
        session.add(ApiUsageRow(
            date=_today(), provider="claude", purpose=purpose,
            cost_eur=cost, units=input_tokens + output_tokens,
        ))


def claude_budget_exceeded() -> bool:
    with session_scope() as session:
        spent = daily_usage_eur(session, "claude", _today())
    if spent >= config.CLAUDE_DAILY_BUDGET_EUR:
        logger.warning(f"Claude-Tagesbudget erreicht ({spent:.2f} €) — keine weiteren Calls heute")
        return True
    return False


def record_tts(chars: int, purpose: str) -> None:
    with session_scope() as session:
        session.add(ApiUsageRow(
            date=_today(), provider="elevenlabs", purpose=purpose, cost_eur=0.0, units=chars,
        ))


def tts_budget_exceeded(next_chars: int) -> bool:
    with session_scope() as session:
        used = daily_usage_units(session, "elevenlabs", _today())
    if used + next_chars > config.TTS_DAILY_BUDGET_CHARS:
        logger.warning(f"TTS-Tagesbudget erreicht ({used} Zeichen) — kein Voiceover mehr heute")
        return True
    return False
