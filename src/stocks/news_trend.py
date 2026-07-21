"""Pick the single stock that is most 'in the news / trending' right now, from the
same finance headlines the reel collectors gather, via one budget-gated Claude call.
The pick is validated against yfinance and respects the 30-day repeat cooldown."""
from __future__ import annotations

import json

from loguru import logger

import config
from src.content.llm import LLMProvider, parse_json_response
from src.content.usage import claude_budget_exceeded
from src.stocks.analyzer import analyze_ticker
from src.stocks.market_data import MarketData

_SYSTEM_PROMPT = """Du identifizierst aus aktuellen deutschsprachigen Finanz-Schlagzeilen die \
EINE börsennotierte Aktie, die gerade am stärksten im Fokus / im Trend steht (viel Nachrichten, \
Kursbewegung, Ereignis). Gib einen handelbaren yfinance-Ticker zurück:
- US-Aktien ohne Suffix (AAPL, NVDA, TSLA)
- EU-Aktien MIT Börsensuffix: .DE (Frankfurt), .PA (Paris), .AS (Amsterdam), .L (London), \
.SW (Zürich), .MI (Mailand), .MC (Madrid)
Nur real existierende, liquide Einzelaktien (keine Indizes/ETFs/Krypto). Keine Anlageberatung.
Antworte AUSSCHLIESSLICH mit gültigem JSON, keine doppelten Anführungszeichen in Textwerten."""

_USER_TEMPLATE = """Aktuelle Finanz-Schlagzeilen (heute):
{headlines}

Schließe diese Ticker AUS (wurden zuletzt schon behandelt): {exclude}

Gib genau diese JSON-Struktur zurück:
{{"ticker": "TICK", "name": "Firmenname", "reason": "1 kurzer Satz, warum die Aktie gerade im Trend ist"}}
Wenn keine eindeutige Trend-Aktie erkennbar ist, gib {{"ticker": ""}} zurück."""


def gather_headlines(limit: int = 60) -> list[str]:
    """Recent finance headlines from the active collectors (best-effort, no crash)."""
    from src.collectors.rss import active_collectors

    seen: set[str] = set()
    headlines: list[str] = []
    for collector in active_collectors():
        for item in collector.safe_collect():
            title = (item.title or "").strip()
            if title and title.lower() not in seen:
                seen.add(title.lower())
                headlines.append(title)
    return headlines[:limit]


def pick_trend_ticker(
    headlines: list[str], llm: LLMProvider, exclude: set[str]
) -> tuple[str, str, str] | None:
    """One budget-gated Claude call → (ticker, name, reason), or None."""
    if claude_budget_exceeded():
        logger.warning("Claude-Budget erschöpft — keine Trend-Aktie")
        return None
    payload = "\n".join(f"- {h}" for h in headlines)
    try:
        raw = llm.complete(
            system=_SYSTEM_PROMPT,
            user=_USER_TEMPLATE.format(headlines=payload, exclude=", ".join(sorted(exclude)) or "—"),
            model=config.CLAUDE_MODEL_FAST,
            max_tokens=300,
            purpose="trend_ticker",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Trend-Ticker-Analyse fehlgeschlagen: {exc}")
        return None
    data = parse_json_response(raw)
    if not isinstance(data, dict):
        return None
    ticker = str(data.get("ticker", "")).strip().upper()
    if not ticker:
        return None
    return ticker, str(data.get("name", ticker)).strip(), str(data.get("reason", "")).strip()


def select_trend_ticker(
    md: MarketData, llm: LLMProvider, exclude: set[str]
) -> tuple[str, str, str] | None:
    """Gather headlines → pick a trending ticker not in the cooldown set → validate it
    has yfinance data. Retries once (excluding the failed pick)."""
    headlines = gather_headlines()
    if not headlines:
        logger.info("Keine aktuellen Schlagzeilen — keine Trend-Aktie heute")
        return None

    blocked = {t.upper() for t in exclude}
    for _ in range(2):
        pick = pick_trend_ticker(headlines, llm, blocked)
        if pick is None:
            return None
        ticker, name, reason = pick
        if ticker in blocked:
            blocked.add(ticker)
            continue
        if analyze_ticker(md, ticker) is None:
            logger.warning(f"Trend-Ticker {ticker} ohne verwertbare Marktdaten — neuer Versuch")
            blocked.add(ticker)
            continue
        logger.info(f"Trend-Aktie: {ticker} ({reason[:80]})")
        return ticker, name, reason
    return None
