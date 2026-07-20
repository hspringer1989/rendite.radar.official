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

_SYSTEM_PROMPT = """Du bist ein quantitativer Finanzanalyst und erklärst für ein deutsches \
Instagram-Finanz-Bildungsprofil FUNDIERT und knapp, was Charttechnik und Fundamentaldaten \
zu einer Aktie AKTUELL zeigen.

ANSPRUCH — der Text muss substanziell sein, KEINE Floskeln:
- Nenne die KONKRETEN Zahlen aus den Daten und interpretiere sie (nicht nur wiederholen):
  · Charttechnik: Kurs relativ zur 20- und 50-Tage-Linie (Trendstruktur), RSI-Wert \
(>70 überkauft/Rücksetzer-Risiko, <30 überverkauft, 45–65 gesund), Abstand von der aktuellen \
Referenz zur Risikomarke (Stop) und Potenzialmarke (Ziel).
  · Fundamental: KGV (teuer/günstig, grob <15 günstig, >30 teuer), Umsatzwachstum, Gewinnmarge.
- Formuliere eine klare KERNAUSSAGE (These), nicht nur Adjektive. \
Schlecht: "solide bewertet". Gut: "Mit KGV 11 klar günstiger als der Gesamtmarkt, das Umsatzplus von 15% stützt das."
- Dicht und knapp: 2–3 Sätze je Card. Alltagsnah, Fachbegriffe in einem Halbsatz erklärt.

STRIKTE COMPLIANCE (BaFin/MAR, keine Ausnahmen):
- Beobachtend, KEINE Kauf-/Verkaufsempfehlung ("Der Chart zeigt…", NIEMALS "Kaufen"/"Einsteigen").
- Ampel und Marken beschreiben die DATEN, nicht eine Handlung. Immer Chance UND Risiko benennen. \
Keine Rendite-Versprechen.

WICHTIG für gültiges JSON: INNERHALB der Textwerte KEINE doppelten Anführungszeichen (") und \
keine Zeilenumbrüche verwenden.
Antworte AUSSCHLIESSLICH mit gültigem JSON, kein Fließtext, keine Markdown-Umrandung."""

_USER_TEMPLATE = """Analysiere die folgenden {n} Watchlist-Titel quantitativ. Gib je Titel DREI \
dichte, fundierte Texte: Charttechnik, Fundamental, Gesamtbild. Nutze die konkreten Zahlen unten \
und interpretiere sie — jeder Satz soll etwas aussagen.

Daten je Titel (Ampel-Level ist vorgegeben, richte den Ton daran aus):
{payload}

Gib genau diese JSON-Struktur zurück:
{{
  "candidates": [
    {{
      "ticker": "TICK",
      "chart": "2-3 dichte Sätze mit Zahlen: Trendstruktur (Kurs vs. SMA20/SMA50), RSI-Lage, Abstand zu Stop/Ziel",
      "fundamental": "2-3 dichte Sätze mit Zahlen: KGV (teuer/günstig), Wachstum, Marge — was das konkret heißt",
      "overall": "1-2 Sätze: passen Chart und Fundamental zusammen? Wichtigste Chance und wichtigstes Risiko"
    }}
  ]
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
        history_closes=[round(c, 2) for c in closes[-90:]],
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


def _fallback_texts(c: Candidate) -> tuple[str, str, str]:
    """Rule-based, data-citing educational texts (chart, fundamental, overall) used
    when Claude is unavailable / over budget. Concrete numbers, not filler."""
    m = c.metrics
    pos20 = "über" if m.price > m.sma20 else "unter"
    pos50 = "über" if m.price > m.sma50 else "unter"
    trend = ("ein intakter Aufwärtstrend" if m.price > m.sma50 and m.sma20 > m.sma50
             else "ein angeschlagener Trend" if m.price < m.sma50
             else "eine Seitwärtsphase")
    if m.rsi >= 70:
        rsi_note = "überkauft, kurzfristig steigt das Rücksetzer-Risiko"
    elif m.rsi <= 30:
        rsi_note = "überverkauft, technisch stark gefallen"
    elif 45 <= m.rsi <= 65:
        rsi_note = "im gesunden Bereich"
    else:
        rsi_note = "neutral"
    down = (c.entry - c.stop_loss) / c.entry * 100 if c.entry else 0
    up = (c.take_profit - c.entry) / c.entry * 100 if c.entry else 0
    chart = (
        f"Der Kurs steht {pos20} der 20- und {pos50} der 50-Tage-Linie – {trend}. "
        f"Der RSI (Schwungkraft-Maß) liegt bei {m.rsi:.0f}, also {rsi_note}. "
        f"Bis zur Risikomarke sind es ca. {down:.0f}%, bis zur Zielmarke ca. {up:.0f}%. Beobachtung, keine Empfehlung."
    )

    pe = f"{m.pe:.0f}" if m.pe else None
    val = ("günstig bewertet" if (m.pe and m.pe < 15)
           else "moderat bewertet" if (m.pe and m.pe < 30)
           else "hoch bewertet" if m.pe else "ohne belastbares KGV")
    growth = f"{m.revenue_growth * 100:.0f}%" if m.revenue_growth is not None else "n/a"
    margin = f"{m.profit_margin * 100:.0f}%" if m.profit_margin is not None else "n/a"
    fund = (
        f"Mit einem KGV von {pe or 'n/a'} ist die Aktie {val} (KGV = Preis je Euro Jahresgewinn). "
        f"Das Umsatzwachstum liegt bei {growth}, die Gewinnmarge bei {margin}. "
        f"Datenbasierte Einordnung, keine Empfehlung."
    )

    aligned = (m.price > m.sma50) == (m.fund_score >= 0.5)
    overall = (
        f"Charttechnik und Fundamentaldaten {'stützen sich gegenseitig' if aligned else 'ziehen unterschiedlich'} "
        f"(Chart-Score {m.tech_score:.2f}, Fundamental-Score {m.fund_score:.2f}). "
        f"Chance ist die Zielmarke, Risiko der Rückfall unter die Stop-Marke. Keine Empfehlung."
    )
    return chart, fund, overall


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


def _apply_fallback(candidates: list[Candidate]) -> None:
    for c in candidates:
        c.chart_text, c.fundamental_text, c.overall_text = _fallback_texts(c)


def _attach_analysis(candidates: list[Candidate], llm: LLMProvider) -> None:
    """Fill the three educational texts per candidate via one budget-gated Claude call;
    rule-based fallback on budget/LLM failure."""
    if claude_budget_exceeded():
        logger.warning("Claude-Budget erschöpft — nutze regelbasierte Analysetexte")
        _apply_fallback(candidates)
        return

    payload = json.dumps([
        {
            "ticker": c.metrics.ticker, "name": c.metrics.name, "sector": c.metrics.sector,
            "price": c.metrics.price, "currency": c.metrics.currency,
            "sma20": c.metrics.sma20, "sma50": c.metrics.sma50, "rsi": c.metrics.rsi,
            "pe": c.metrics.pe, "revenue_growth": c.metrics.revenue_growth,
            "profit_margin": c.metrics.profit_margin,
            "risk_mark": c.stop_loss, "potential_mark": c.take_profit,
            "chart_ampel": ind.tendency(c.metrics.tech_score, "chart")[1],
            "fundamental_ampel": ind.tendency(c.metrics.fund_score, "fund")[1],
            "gesamt_ampel": ind.tendency(c.metrics.blended, "overall")[1],
        }
        for c in candidates
    ], ensure_ascii=False)

    user = _USER_TEMPLATE.format(n=len(candidates), payload=payload)
    data = None
    for attempt in range(2):  # one retry: the model occasionally emits invalid JSON
        try:
            raw = llm.complete(
                system=_SYSTEM_PROMPT, user=user,
                model=config.CLAUDE_MODEL, max_tokens=2600, purpose="stock_analysis",
            )
        except Exception as exc:  # noqa: BLE001 — never crash the daily run on the LLM
            logger.warning(f"Claude-Analyse fehlgeschlagen ({exc}) — regelbasierte Texte")
            _apply_fallback(candidates)
            return
        data = parse_json_response(raw)
        if isinstance(data, dict) and data.get("candidates"):
            break
        logger.warning(f"Analyse-JSON ungültig (Versuch {attempt + 1}/2)")

    by_ticker: dict[str, dict] = {}
    if isinstance(data, dict):
        for entry in data.get("candidates", []):
            if isinstance(entry, dict) and entry.get("ticker"):
                by_ticker[str(entry["ticker"]).upper()] = entry

    for c in candidates:
        entry = by_ticker.get(c.metrics.ticker.upper())
        fb_chart, fb_fund, fb_overall = _fallback_texts(c)
        if entry:
            c.chart_text = _sanitise(str(entry.get("chart", "")).strip()) or fb_chart
            c.fundamental_text = _sanitise(str(entry.get("fundamental", "")).strip()) or fb_fund
            c.overall_text = _sanitise(str(entry.get("overall", "")).strip()) or fb_overall
        else:
            c.chart_text, c.fundamental_text, c.overall_text = fb_chart, fb_fund, fb_overall
