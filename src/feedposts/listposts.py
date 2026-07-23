"""Generic 'stock list with two traffic lights' feed post — like the dividend post,
but with a FREELY CHOSEN metric column (KGV, distance from 52-week high, …). Includes
screens for undervalued-quality and near-52-week-low stocks. Educational framing only."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

import config
from src import branding
from src.feedposts import renderer as fr
from src.models import Slide, StockMetrics
from src.stocks import indicators as ind
from src.stocks.analyzer import analyze_ticker
from src.stocks.market_data import MarketData, get_market_data
from src.storage.database import FeedPostRow, session_scope

_ROWS_PER_SLIDE = 7
_COL_METRIC = 600
_CX_CHART = 852
_CX_FUND = 968
_ROW_H = 88


@dataclass
class ListRow:
    ticker: str
    name: str
    market: str
    metric: str        # pre-formatted display value, e.g. "14,5" or "-28%"
    chart_level: str
    fund_level: str


def _dot(draw, cx: int, cy: int, level: str) -> None:
    r = 20
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=branding.LIGHT.get(level, branding.MUTED))


def _render_table(rows: list[ListRow], metric_label: str, index: int, total: int, out: str) -> str:
    from PIL import ImageDraw

    top, header_h = 165, 66
    bottom = top + header_h + len(rows) * _ROW_H + 30
    base = fr._panel(fr._open_bg(config.FEED_TEMPLATE_TITLE), (40, top - 40, fr.W - 40, bottom), 216)
    draw = ImageDraw.Draw(base)
    fr._counter(draw, index, total)

    hf = branding.load_font(26, bold=True)
    draw.text((88, top), "Aktie", font=hf, fill=branding.MUTED)
    draw.text((_COL_METRIC, top), metric_label, font=hf, fill=branding.MUTED)
    draw.text((_CX_CHART - 46, top), "Chart", font=hf, fill=branding.MUTED)
    draw.text((_CX_FUND - 40, top), "Fund.", font=hf, fill=branding.MUTED)

    tf = branding.load_font(40, bold=True)
    nf = branding.load_font(26)
    mf = branding.load_font(38, bold=True)
    y = top + header_h
    for r in rows:
        draw.text((88, y + 6), r.ticker, font=tf, fill=branding.BLUE)
        # place the name after the ticker (dynamic) so long EU tickers never overlap it
        name_x = max(300, int(88 + draw.textlength(r.ticker, font=tf)) + 24)
        draw.text((name_x, y + 18), r.name[:14], font=nf, fill=branding.FG)
        draw.text((_COL_METRIC, y + 10), r.metric, font=mf, fill=branding.FG)
        _dot(draw, _CX_CHART, y + 36, r.chart_level)
        _dot(draw, _CX_FUND, y + 36, r.fund_level)
        y += _ROW_H
    return fr._save(base, out)


def build_list_post(slug: str, title: str, hook_body: str, explainer_body: str,
                    summary_body: str, caption: str, rows: list[ListRow], metric_label: str,
                    scheduled_at: str = "") -> int | None:
    """Render (hook → explainer → table(s) → summary) + persist a FeedPostRow."""
    if len(rows) < 4:
        logger.warning(f"Zu wenige Titel für '{slug}' ({len(rows)}) — kein Post")
        return None
    stamp = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y%m%d_%H%M%S")
    out = Path(config.FEED_DIR)
    chunks = [rows[i:i + _ROWS_PER_SLIDE] for i in range(0, len(rows), _ROWS_PER_SLIDE)]
    total = 2 + len(chunks) + 1
    paths: list[str] = []
    paths.append(fr._render_hero(Slide(title, hook_body), 0, total, False,
                                 str(out / f"{slug}_hook_{stamp}.jpg")))
    paths.append(fr._render_content(Slide("So liest du die Tabelle", explainer_body), 1, total,
                                    str(out / f"{slug}_info_{stamp}.jpg")))
    for i, chunk in enumerate(chunks):
        paths.append(_render_table(chunk, metric_label, 2 + i, total,
                                   str(out / f"{slug}_tab{i}_{stamp}.jpg")))
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
    logger.info(f"Listen-Post #{post_id} '{slug}' ({len(rows)} Titel, {len(paths)} Slides)")
    return post_id


def _row(m: StockMetrics, metric: str) -> ListRow:
    return ListRow(m.ticker, m.name, m.market, metric,
                   ind.tendency(m.tech_score, "chart")[0], ind.tendency(m.fund_score, "fund")[0])


# ── screens ────────────────────────────────────────────────────────────────
def screen_undervalued_quality(md: MarketData, universe: list[str], count: int = 12) -> list[ListRow]:
    """Cheap (low P/E) AND fundamentally strong (green Fundamental light), by P/E asc."""
    hits: list[tuple[float, ListRow]] = []
    for t in universe:
        m = analyze_ticker(md, t)
        if m is None or m.pe is None or not (0 < m.pe < 25):
            continue
        if ind.tendency(m.fund_score, "fund")[0] != "pos":   # only strong fundamentals
            continue
        hits.append((m.pe, _row(m, f"{m.pe:.1f}".replace(".", ","))))
    hits.sort(key=lambda x: x[0])
    return [r for _, r in hits[:count]]


def screen_near_52w_low(md: MarketData, universe: list[str], count: int = 12) -> list[ListRow]:
    """Biggest drop from the 52-week high (metric = distance from high, most negative first)."""
    hits: list[tuple[float, ListRow]] = []
    for t in universe:
        m = analyze_ticker(md, t)
        if m is None or not m.high_52w or m.high_52w <= 0 or not m.price:
            continue
        drop = (m.price - m.high_52w) / m.high_52w * 100    # negative
        if drop >= -1:                                       # skip ones basically at their high
            continue
        hits.append((drop, _row(m, f"{drop:.0f}%")))
    hits.sort(key=lambda x: x[0])                            # most negative first
    return [r for _, r in hits[:count]]


def build_undervalued_post(md: MarketData | None = None, scheduled_at: str = "") -> int | None:
    md = md or get_market_data()
    rows = screen_undervalued_quality(md, config.STOCK_UNIVERSE)
    caption = (
        "5 unterbewertete Qualitätsaktien 🔎 — günstige Bewertung (niedriges KGV) trifft auf "
        "eine starke Fundamental-Ampel. Plus der Chart-Check.\n\n"
        "Günstig ist nicht gleich gut — deshalb der Ampel-Filter.\n\n"
        f"Folge {config.BRAND_HANDLE} für mehr 📈\n\n"
        "⚠️ Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung\n"
        "#aktien #unterbewertet #valueinvesting #kgv #qualitätsaktien #finanzen #börse"
    )
    return build_list_post(
        "unterbewertete-qualitaet", "Unterbewertete Qualitätsaktien im Ampel-Check",
        "Günstig bewertet UND fundamental stark — diese Kombination suchen wir. Niedriges KGV "
        "allein reicht nicht, deshalb muss die Fundamental-Ampel grün sein.",
        "KGV = Kurs-Gewinn-Verhältnis (wie viel du je Euro Jahresgewinn zahlst, niedriger = "
        "günstiger). Die zwei Ampeln zeigen Charttechnik und Fundamental (grün/gelb/rot). Hier "
        "sind alle fundamental grün gefiltert und nach KGV sortiert. Keine Empfehlung.",
        "Günstig plus starke Substanz ist die interessante Kombination — aber prüfe immer, WARUM "
        "eine Aktie günstig ist. Die Ampeln helfen dabei. Keine Anlageberatung.",
        caption, rows, "KGV", scheduled_at,
    )


def build_52w_low_post(md: MarketData | None = None, scheduled_at: str = "") -> int | None:
    md = md or get_market_data()
    rows = screen_near_52w_low(md, config.STOCK_UNIVERSE)
    caption = (
        "Schnäppchen oder fallendes Messer? 🔪 — diese Aktien sind am weitesten von ihrem "
        "52-Wochen-Hoch entfernt. Was sagt die Ampel dazu?\n\n"
        "Ein tiefer Kurs allein ist kein Kaufgrund — die Ampeln zeigen, ob Substanz dahinter steht.\n\n"
        f"Folge {config.BRAND_HANDLE} für mehr 📈\n\n"
        "⚠️ Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung\n"
        "#aktien #börse #schnäppchen #charttechnik #finanzen #investieren"
    )
    return build_list_post(
        "52-wochen-tief", "52-Wochen-Tief: Schnäppchen oder fallendes Messer?",
        "Stark gefallene Aktien reizen — aber sind sie günstig oder zu Recht abgestraft? Diese "
        "Titel sind am weitesten von ihrem 52-Wochen-Hoch weg. Die Ampel hilft beim Einordnen.",
        "Die Spalte zeigt den Abstand zum 52-Wochen-Hoch (z.B. -30% = 30% unter dem Jahreshoch). "
        "Die zwei Ampeln zeigen Charttechnik und Fundamental (grün/gelb/rot). Rot bei Fundamental "
        "heißt oft: zu Recht gefallen. Keine Empfehlung.",
        "Ein tiefer Kurs ist kein Kaufgrund an sich. Grüne Fundamental-Ampel + tiefer Kurs = "
        "genauer hinschauen; rote Ampel = oft ein fallendes Messer. Keine Anlageberatung.",
        caption, rows, "vom Hoch", scheduled_at,
    )
