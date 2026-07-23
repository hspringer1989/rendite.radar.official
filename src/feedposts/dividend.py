"""Data-driven feed post: monthly-dividend payers with a per-stock traffic-light for
Charttechnik and Fundamental. Reuses the feed review/publish path (a FeedPostRow), so
it goes through Telegram approval → immediate post → announcement story like any feed
post. Educational framing only (no advice)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

import config
from src import branding
from src.content.llm import LLMProvider
from src.feedposts import renderer as fr
from src.models import Slide
from src.stocks import indicators as ind
from src.stocks.analyzer import analyze_ticker
from src.stocks.market_data import MarketData, get_market_data
from src.storage.database import FeedPostRow, session_scope

_ROWS_PER_SLIDE = 7
_COL_YIELD = 620
_CX_CHART = 852
_CX_FUND = 968
_ROW_H = 88


@dataclass
class DivRow:
    ticker: str
    name: str
    market: str
    yield_pct: float | None
    chart_level: str   # pos | neu | neg
    fund_level: str


def _norm_yield(v: float | None) -> float | None:
    """yfinance returns dividendYield as a fraction (0.055) on some versions and as a
    percent (5.5) on others — normalise to a percent number."""
    if v is None:
        return None
    return round(v * 100, 1) if v <= 1 else round(v, 1)


def build_dividend_rows(md: MarketData, tickers: list[str] | None = None) -> list[DivRow]:
    """Analyse the given (or monthly-dividend) tickers into rows (yield + two lights)."""
    tickers = tickers if tickers is not None else config.DIVIDEND_MONTHLY_TICKERS
    rows: list[DivRow] = []
    for ticker in tickers:
        m = analyze_ticker(md, ticker)
        if m is None:
            continue
        rows.append(DivRow(
            ticker=ticker, name=m.name, market=m.market,
            yield_pct=_norm_yield(m.dividend_yield),
            chart_level=ind.tendency(m.tech_score, "chart")[0],
            fund_level=ind.tendency(m.fund_score, "fund")[0],
        ))
    rows.sort(key=lambda r: (r.yield_pct or 0), reverse=True)
    return rows


def _dot(draw, cx: int, cy: int, level: str) -> None:
    r = 20
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=branding.LIGHT.get(level, branding.MUTED))


def _render_table(rows: list[DivRow], index: int, total: int, out_path: str) -> str:
    from PIL import ImageDraw

    top, header_h = 165, 66
    bottom = top + header_h + len(rows) * _ROW_H + 30
    base = fr._panel(fr._open_bg(config.FEED_TEMPLATE_TITLE), (40, top - 40, fr.W - 40, bottom), 216)
    draw = ImageDraw.Draw(base)
    fr._counter(draw, index, total)

    hf = branding.load_font(26, bold=True)
    draw.text((88, top), "Aktie", font=hf, fill=branding.MUTED)
    draw.text((_COL_YIELD, top), "Rendite", font=hf, fill=branding.MUTED)
    draw.text((_CX_CHART - 46, top), "Chart", font=hf, fill=branding.MUTED)
    draw.text((_CX_FUND - 40, top), "Fund.", font=hf, fill=branding.MUTED)

    tf = branding.load_font(40, bold=True)
    nf = branding.load_font(26)
    yf = branding.load_font(38, bold=True)
    y = top + header_h
    for r in rows:
        draw.text((88, y + 6), r.ticker, font=tf, fill=branding.BLUE)
        draw.text((252, y + 16), r.name[:16], font=nf, fill=branding.FG)
        yp = f"{r.yield_pct:.1f}%".replace(".", ",") if r.yield_pct is not None else "—"
        draw.text((_COL_YIELD, y + 10), yp, font=yf, fill=branding.FG)
        _dot(draw, _CX_CHART, y + 36, r.chart_level)
        _dot(draw, _CX_FUND, y + 36, r.fund_level)
        y += _ROW_H
    return fr._save(base, out_path)


def build_list_post(
    slug: str, title: str, hook_body: str, explainer_body: str, summary_body: str,
    caption: str, tickers: list[str], md: MarketData | None = None,
    scheduled_at: str = "",
) -> int | None:
    """Generic 'stock list with two traffic lights' feed post (hook → explainer →
    table slides → summary). Reusable for dividend/aristocrat/other screens.
    Persists a FeedPostRow(pending_review); returns its id."""
    md = md or get_market_data()
    rows = build_dividend_rows(md, tickers)
    if len(rows) < 4:
        logger.warning(f"Zu wenige Titel mit Daten für '{slug}' ({len(rows)}) — kein Post")
        return None

    stamp = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M%S")
    out = Path(config.FEED_DIR)
    chunks = [rows[i:i + _ROWS_PER_SLIDE] for i in range(0, len(rows), _ROWS_PER_SLIDE)]
    total = 2 + len(chunks) + 1  # hook + explainer + table(s) + summary
    paths: list[str] = []

    paths.append(fr._render_hero(Slide(title, hook_body), 0, total, False,
                                 str(out / f"{slug}_hook_{stamp}.jpg")))
    paths.append(fr._render_content(Slide("So liest du die Tabelle", explainer_body), 1, total,
                                    str(out / f"{slug}_info_{stamp}.jpg")))
    for i, chunk in enumerate(chunks):
        paths.append(_render_table(chunk, 2 + i, total, str(out / f"{slug}_tab{i}_{stamp}.jpg")))
    paths.append(fr._render_hero(Slide("Zusammenfassung", summary_body), total - 1, total, True,
                                 str(out / f"{slug}_sum_{stamp}.jpg")))

    with session_scope() as session:
        row = FeedPostRow(
            topic_slug=slug, title=title,
            slides_json=json.dumps([asdict(r) for r in rows], ensure_ascii=False),
            image_paths_json=json.dumps(paths, ensure_ascii=False),
            caption=caption, status="pending_review", scheduled_at=scheduled_at,
        )
        session.add(row)
        session.flush()
        post_id = row.id
    logger.info(f"Listen-Post #{post_id} '{slug}' erstellt ({len(rows)} Titel, {len(paths)} Slides)")
    return post_id


def build_dividend_post(md: MarketData | None = None, llm: LLMProvider | None = None,
                        scheduled_at: str = "") -> int | None:
    """The monthly-dividend list post."""
    caption = (
        "Jeden Monat Dividende 📅 — Monatszahler für regelmäßigen Cashflow, mit unserem "
        "Ampel-Check aus Charttechnik & Fundamental.\n\n"
        "Welcher Monatszahler fehlt? Schreib's in die Kommentare!\n\n"
        f"Folge {config.BRAND_HANDLE} für mehr 📈\n\n"
        "⚠️ Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung\n"
        "#dividende #passiveseinkommen #aktien #cashflow #monatszahler #finanzen #börse #reit"
    )
    return build_list_post(
        "dividende-monatszahler", "Jeden Monat Dividende – Monatszahler mit Ampel-Check",
        "Diese Aktien zahlen MONATLICH aus — plus unser Ampel-Check aus Charttechnik "
        "und Fundamental für jeden Titel.",
        "Rendite = Dividendenrendite pro Jahr. Die zwei Ampeln zeigen unsere datenbasierte "
        "Einschätzung: Chart = Charttechnik, Fund = Fundamental (grün/gelb/rot). Wichtig: eine "
        "hohe Rendite ist nicht automatisch gut — die Ampeln zeigen, was die Daten sagen. Keine Empfehlung.",
        "Monatszahler bringen regelmäßigen Cashflow ins Depot. Achte nicht nur auf die Rendite, "
        "sondern auch auf die Substanz dahinter — dafür die Ampeln. Keine Anlageberatung.",
        caption, config.DIVIDEND_MONTHLY_TICKERS, md, scheduled_at,
    )


def build_aristocrats_post(md: MarketData | None = None, llm: LLMProvider | None = None,
                           scheduled_at: str = "") -> int | None:
    """Dividend-Aristocrats list post (25+ years of rising dividends) with the Ampel-Check."""
    caption = (
        "Dividenden-Aristokraten 👑 — Aktien, die ihre Dividende seit über 25 Jahren JEDES "
        "Jahr erhöhen. Mit unserem Ampel-Check aus Charttechnik & Fundamental.\n\n"
        "Historie ist stark — aber zählt heute die Substanz? Genau das zeigen die Ampeln.\n\n"
        f"Folge {config.BRAND_HANDLE} für mehr 📈\n\n"
        "⚠️ Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung\n"
        "#dividende #dividendenaristokraten #qualitätsaktien #passiveseinkommen #aktien #finanzen #börse"
    )
    return build_list_post(
        "dividenden-aristokraten", "Dividenden-Aristokraten: 25+ Jahre Erhöhung",
        "Diese Aktien erhöhen ihre Dividende seit über 25 Jahren — jedes Jahr. Ein Zeichen für "
        "Stabilität. Plus unser Ampel-Check aus Charttechnik und Fundamental.",
        "Ein Dividenden-Aristokrat hat seine Dividende mindestens 25 Jahre in Folge erhöht — das "
        "spricht für Preissetzungsmacht und Verlässlichkeit. Aber Vergangenheit ist keine Garantie: "
        "Rendite = Dividendenrendite p.a., die zwei Ampeln (Chart/Fundamental, grün/gelb/rot) zeigen "
        "die aktuelle Datenlage. Keine Empfehlung.",
        "Aristokraten stehen für verlässliches Dividendenwachstum — aber prüfe die aktuelle Substanz "
        "über die Ampeln, nicht nur die Historie. Keine Anlageberatung.",
        caption, config.DIVIDEND_ARISTOCRAT_TICKERS, md, scheduled_at,
    )
