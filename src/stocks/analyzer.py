"""Turns the ticker universe into 3–4 sector-diversified watchlist candidates:
compute chart+fundamental metrics, derive chart-based risk marks, then one
budget-gated Claude call writes the educational analysis text + overall take.

Compliance: framing is educational/watchlist, NEVER a buy recommendation. The
system prompt forbids directive language; a code-side safety net enforces the
disclaimer and neutralises the most blatant imperatives."""
from __future__ import annotations

import json

from loguru import logger

import config
from src.content.llm import LLMProvider, parse_json_response
from src.content.usage import claude_budget_exceeded
from src.models import Candidate, StockMetrics
from src.stocks import indicators as ind
from src.stocks.market_data import MarketData

_DISCLAIMER = "⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung. Kein Kauf-/Verkaufsaufruf."

_SYSTEM_PROMPT = """Du bist ein nüchterner Finanz-Analyst und erklärst für ein deutsches \
Finanz-Bildungsprofil, was Charttechnik und Fundamentaldaten zu einer Aktie AKTUELL zeigen.

STRIKTE COMPLIANCE (BaFin-Finfluencer-Regeln, keine Ausnahmen):
- KEINE Anlageberatung, KEINE Kaufempfehlung. Schreibe beobachtend/erklärend \
("Die Charttechnik zeigt…", "Fundamental fällt auf…"), NIEMALS direktiv ("Kaufen", "Jetzt einsteigen").
- Stop-Loss / Take-Profit sind als CHARTTECHNISCHE Risiko- bzw. Potenzialmarken zu erklären \
("aus Risikosicht würde eine Marke bei X liegen"), nicht als Handlungsanweisung.
- Keine Rendite-Versprechen, keine Sicherheit suggerieren. Chancen UND Risiken nennen.
- Sachlich, konkret, mit den gelieferten Zahlen. Deutsch, pro Aktie 2–3 kurze Sätze.

Antworte AUSSCHLIESSLICH mit gültigem JSON, kein Fließtext, keine Markdown-Umrandung."""

_USER_TEMPLATE = """Erkläre edukativ die folgenden {n} Watchlist-Titel (unterschiedliche Branchen), \
je auf Basis von Charttechnik UND Fundamentaldaten. Gib zusätzlich eine sachliche \
Gesamteinordnung ("overall").

Titel-Daten:
{payload}

Gib genau diese JSON-Struktur zurück:
{{
  "candidates": [
    {{"ticker": "TICK", "analysis": "2-3 Sätze edukative Einordnung (Charttechnik + Fundamental + Risiko)"}}
  ],
  "overall": "1-2 Sätze sachliche Gesamteinordnung der Auswahl"
}}"""

# Blatant imperatives that must never survive into a public caption.
_BANNED = ("kaufen", "jetzt einsteigen", "jetzt kaufen", "unbedingt", "sofort zuschlagen")


def analyze_ticker(md: MarketData, ticker: str) -> StockMetrics | None:
    """Compute a full chart+fundamental snapshot for one ticker, or None on missing data."""
    bars = md.history(ticker)
    info = md.info(ticker)
    if not bars or not info or not bars.get("close"):
        logger.debug(f"{ticker}: keine ausreichenden Marktdaten")
        return None

    closes = bars["close"]
    price = closes[-1]
    sma20 = ind.sma(closes, 20)
    sma50 = ind.sma(closes, 50)
    rsi_value = ind.rsi(closes)
    atr_value = ind.atr(bars["high"], bars["low"], closes)
    mom = ind.momentum(closes)
    fund = md.fundamentals(ticker)

    return StockMetrics(
        ticker=ticker,
        name=info["name"],
        sector=info["sector"],
        market=info["market"],
        price=round(price, 2),
        currency=info["currency"],
        sma20=round(sma20 or price, 2),
        sma50=round(sma50 or price, 2),
        rsi=round(rsi_value or 50.0, 1),
        atr=round(atr_value or 0.0, 2),
        tech_score=ind.technical_score(price, sma20, sma50, rsi_value, mom),
        fund_score=ind.fundamental_score(
            fund.get("pe"), fund.get("revenue_growth"), fund.get("profit_margin")
        ),
        pe=fund.get("pe"),
        revenue_growth=fund.get("revenue_growth"),
        profit_margin=fund.get("profit_margin"),
    )


def select_candidates(
    md: MarketData, universe: list[str], count: int
) -> list[StockMetrics]:
    """Score the whole universe and pick the top `count` by blended score, keeping
    each from a DISTINCT sector (diversification, like the factor strategy)."""
    scored = [m for t in universe if (m := analyze_ticker(md, t)) is not None]
    scored.sort(key=lambda m: m.blended, reverse=True)

    picked: list[StockMetrics] = []
    seen_sectors: set[str] = set()
    for m in scored:
        if m.sector in seen_sectors:
            continue
        picked.append(m)
        seen_sectors.add(m.sector)
        if len(picked) >= count:
            break
    # Top up from the remainder if too few distinct sectors were available.
    if len(picked) < count:
        for m in scored:
            if m not in picked:
                picked.append(m)
            if len(picked) >= count:
                break
    return picked


def _sanitise(text: str) -> str:
    """Compliance safety net: strip blatant buy-imperatives a sloppy model might emit."""
    cleaned = text.strip()
    lowered = cleaned.lower()
    for bad in _BANNED:
        if bad in lowered:
            logger.warning(f"KI-Analysetext enthielt '{bad}' — neutralisiert")
            # Replace case-insensitively with a neutral phrasing.
            idx = lowered.find(bad)
            cleaned = cleaned[:idx] + "beobachten" + cleaned[idx + len(bad):]
            lowered = cleaned.lower()
    return cleaned


def _fallback_text(m: StockMetrics) -> str:
    """Rule-based educational text used when Claude is unavailable / over budget."""
    trend = "über" if m.price > m.sma50 else "unter"
    return (
        f"Charttechnik: Kurs {trend} der 50-Tage-Linie, RSI bei {m.rsi:.0f}. "
        f"Fundamental: Tech-Score {m.tech_score:.2f}, Fundamental-Score {m.fund_score:.2f}. "
        f"Rein datenbasierte Einordnung, keine Empfehlung."
    )


def build_candidates(
    md: MarketData, universe: list[str], llm: LLMProvider, count: int | None = None
) -> list[Candidate]:
    """Full path: select → risk marks → one educational Claude call for the texts."""
    count = count or config.STOCK_CANDIDATES_COUNT
    metrics = select_candidates(md, universe, count)
    if not metrics:
        logger.warning("Keine Kandidaten mit ausreichenden Daten gefunden")
        return []

    candidates: list[Candidate] = []
    for m in metrics:
        stop, take = ind.risk_levels(
            m.price, m.atr, config.STOCK_ATR_STOP_MULT, config.STOCK_ATR_TP_MULT
        )
        candidates.append(Candidate(metrics=m, entry=m.price, stop_loss=stop, take_profit=take))

    _attach_analysis(candidates, llm)
    return candidates


def _attach_analysis(candidates: list[Candidate], llm: LLMProvider) -> None:
    """Fill Candidate.analysis via one budget-gated Claude call; rule-based fallback."""
    if claude_budget_exceeded():
        logger.warning("Claude-Budget erschöpft — nutze regelbasierte Analysetexte")
        for c in candidates:
            c.analysis = _fallback_text(c.metrics)
        return

    payload = json.dumps([
        {
            "ticker": c.metrics.ticker, "name": c.metrics.name, "sector": c.metrics.sector,
            "price": c.metrics.price, "currency": c.metrics.currency,
            "sma20": c.metrics.sma20, "sma50": c.metrics.sma50, "rsi": c.metrics.rsi,
            "tech_score": c.metrics.tech_score, "fund_score": c.metrics.fund_score,
            "pe": c.metrics.pe, "revenue_growth": c.metrics.revenue_growth,
            "profit_margin": c.metrics.profit_margin,
            "risk_mark": c.stop_loss, "potential_mark": c.take_profit,
        }
        for c in candidates
    ], ensure_ascii=False)

    try:
        raw = llm.complete(
            system=_SYSTEM_PROMPT,
            user=_USER_TEMPLATE.format(n=len(candidates), payload=payload),
            model=config.CLAUDE_MODEL,
            max_tokens=1200,
            purpose="stock_analysis",
        )
    except Exception as exc:  # noqa: BLE001 — never crash the daily run on the LLM
        logger.warning(f"Claude-Analyse fehlgeschlagen ({exc}) — regelbasierte Texte")
        for c in candidates:
            c.analysis = _fallback_text(c.metrics)
        return

    data = parse_json_response(raw)
    texts = {}
    overall = ""
    if isinstance(data, dict):
        for entry in data.get("candidates", []):
            if isinstance(entry, dict) and entry.get("ticker"):
                texts[str(entry["ticker"]).upper()] = str(entry.get("analysis", "")).strip()
        overall = str(data.get("overall", "")).strip()

    for c in candidates:
        text = texts.get(c.metrics.ticker.upper())
        c.analysis = _sanitise(text) if text else _fallback_text(c.metrics)

    if overall:
        # Stash the overall take on the first candidate for the overview card.
        candidates[0].analysis = f"{candidates[0].analysis}\n\nGesamtbild: {_sanitise(overall)}"
