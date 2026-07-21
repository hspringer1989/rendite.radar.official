"""Renders 1080×1920 Instagram-story cards with Pillow. Story stickers/links are
NOT available via the Graph API, so every bit of text (incl. the disclaimer, the
traffic-light signal and the chart-derived risk marks) is baked into the image.

Per candidate we render THREE cards (one story, three frames):
  1) Charttechnik — with a drawn price chart + chart traffic light
  2) Fundamental  — key figures + fundamental traffic light
  3) Gesamtbild   — combined traffic light + recap
The traffic light (green/amber/red) is an OBSERVATIONAL read of the data
(bullish/neutral/bearish), never a buy/sell instruction (BaFin/MAR framing).

Pillow is imported lazily so the rest of the pipeline imports without it."""
from __future__ import annotations

import textwrap
from pathlib import Path

import config
from src import branding
from src.models import Candidate, EarningsItem
from src.stocks import indicators as ind

W, H = 1080, 1920
_BG = branding.BG
_FG = branding.FG
_MUTED = branding.MUTED
_CARD = branding.CARD
_BRAND = branding.BLUE       # brand accent (header, ticker, badges)
_ACCENT = branding.GREEN     # semantic "up/target/positive" (traffic light, TP line)
_AMBER = branding.AMBER
_RED = branding.RED
_BLUE = branding.BLUE_LIGHT  # SMA20 chart overlay
_LIGHT = branding.LIGHT
_font = branding.load_font
_market_badge = branding.market_badge


def _new_card():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)
    draw.text((60, 66), config.BRAND_NAME, font=_font(52, bold=True), fill=_BRAND)
    if config.BRAND_HANDLE:
        draw.text((62, 128), config.BRAND_HANDLE, font=_font(28), fill=_MUTED)
    _footer(draw)
    return img, draw


def _footer(draw) -> None:
    disclaimer = "Keine Anlageberatung · keine Kauf-/Verkaufsempfehlung · Werbung"
    draw.line((60, H - 150, W - 60, H - 150), fill=_MUTED, width=2)
    draw.text((60, H - 130), disclaimer, font=_font(26), fill=_MUTED)


def _wrap(draw, text: str, font, x: int, y: int, width_chars: int, fill, line_h: int) -> int:
    for para in text.split("\n"):
        for line in textwrap.wrap(para, width=width_chars) or [""]:
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h
    return y


def _save(img, out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
    return out_path


def _page_tag(draw, ticker: str, step: str) -> None:
    draw.text((W - 200, 84), step, font=_font(30, bold=True), fill=_MUTED)


def _signal_badge(draw, x: int, y: int, level: str, label: str, big: bool = False) -> None:
    """Traffic-light dot + label. level ∈ {'pos','neu','neg'}."""
    r = 26 if big else 20
    cy = y + (34 if big else 26)
    draw.ellipse((x, cy - r, x + 2 * r, cy + r), fill=_LIGHT.get(level, _MUTED))
    draw.text((x + 2 * r + 20, y + (20 if big else 14)),
              label, font=_font(44 if big else 34, bold=True), fill=_FG)


def _level_row(draw, y: int, label: str, value: str, color) -> None:
    draw.text((90, y), label, font=_font(30), fill=_MUTED)
    draw.text((560, y), value, font=_font(32, bold=True), fill=color)


# ── Chart drawing ──────────────────────────────────────────────────────────
def _draw_chart(draw, box, closes, stop, take, entry, currency) -> None:
    """Simple price line chart with SMA20/50 overlays and stop/target marks."""
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=20, fill=_CARD)
    pad = 30
    ax0, ay0, ax1, ay1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad - 30

    if not closes or len(closes) < 2:
        draw.text((x0 + pad, y0 + pad), "Chartdaten nicht verfügbar", font=_font(30), fill=_MUTED)
        return

    lo = min(min(closes), stop)
    hi = max(max(closes), take)
    if hi <= lo:
        hi = lo + 1.0

    def X(i: int) -> float:
        return ax0 + (ax1 - ax0) * i / (len(closes) - 1)

    def Y(v: float) -> float:
        return ay1 - (ay1 - ay0) * (v - lo) / (hi - lo)

    # horizontal marks: target (green), stop (red), reference (muted)
    for val, col in ((take, _ACCENT), (stop, _RED), (entry, _MUTED)):
        yv = Y(val)
        draw.line((ax0, yv, ax1, yv), fill=col, width=2)
    draw.text((ax0 + 6, Y(take) - 30), f"Ziel {take:.0f} {currency}", font=_font(22), fill=_ACCENT)
    draw.text((ax0 + 6, Y(stop) + 6), f"Stop {stop:.0f} {currency}", font=_font(22), fill=_RED)

    # SMA overlays (drawn under the price line)
    for series, col in ((ind.sma_series(closes, 50), _MUTED), (ind.sma_series(closes, 20), _BLUE)):
        pts = [(X(i), Y(v)) for i, v in enumerate(series) if v is not None]
        if len(pts) > 1:
            draw.line(pts, fill=col, width=2)

    # price line on top
    draw.line([(X(i), Y(v)) for i, v in enumerate(closes)], fill=_FG, width=3)

    # legend
    ly = y1 - 24
    draw.text((ax0, ly), "— Kurs", font=_font(22), fill=_FG)
    draw.text((ax0 + 150, ly), "— 20-Tage", font=_font(22), fill=_BLUE)
    draw.text((ax0 + 330, ly), "— 50-Tage", font=_font(22), fill=_MUTED)


# ── Candidate cards (3 per stock) ──────────────────────────────────────────
def _card_header(draw, c: Candidate, subtitle: str, step: str):
    m = c.metrics
    x = _market_badge(draw, 60, 214, m.market)
    draw.text((x, 190), m.ticker, font=_font(68, bold=True), fill=_FG)
    draw.text((60, 296), f"{m.name}  ·  {m.sector}", font=_font(32), fill=_MUTED)
    draw.text((60, 344), subtitle, font=_font(38, bold=True), fill=_MUTED)
    _page_tag(draw, m.ticker, step)


def render_chart_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    _card_header(draw, c, "1 · Charttechnik", "1/3")

    level, label = ind.tendency(m.tech_score, "chart")
    _signal_badge(draw, 60, 404, level, f"Chart: {label}", big=True)

    _draw_chart(draw, (60, 480, W - 60, 930),
                m.history_closes, c.stop_loss, c.take_profit, c.entry, m.currency)

    # analysis text flows between the chart and the fixed risk-marks box
    _wrap(draw, c.chart_text, _font(32), 60, 968, 46, _FG, 42)

    y = 1500  # fixed so the box always clears the footer, whatever the text length
    draw.rounded_rectangle((60, y, W - 60, y + 232), radius=24, fill=_CARD)
    draw.text((90, y + 22), "Charttechnische Marken (keine Empfehlung)",
              font=_font(28, bold=True), fill=_MUTED)
    _level_row(draw, y + 80, "Referenz (Schluss)", f"{c.entry:.2f} {m.currency}", _FG)
    _level_row(draw, y + 134, "Risikomarke (Stop)", f"{c.stop_loss:.2f} {m.currency}", _RED)
    _level_row(draw, y + 188, "Potenzialmarke (Ziel)", f"{c.take_profit:.2f} {m.currency}", _ACCENT)
    return _save(img, out_path)


def _fig(value, suffix="", pct=False):
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%" if pct else f"{value:.1f}{suffix}"


def render_fundamental_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    _card_header(draw, c, "2 · Fundamental", "2/3")

    level, label = ind.tendency(m.fund_score, "fund")
    _signal_badge(draw, 60, 410, level, f"Fundamental: {label}", big=True)

    y = 540
    draw.rounded_rectangle((60, y, W - 60, y + 300), radius=24, fill=_CARD)
    draw.text((90, y + 22), "Kennzahlen (einfach erklärt)", font=_font(28, bold=True), fill=_MUTED)
    _level_row(draw, y + 80, "KGV (Preis je € Gewinn)", _fig(m.pe), _FG)
    _level_row(draw, y + 134, "Umsatzwachstum", _fig(m.revenue_growth, pct=True), _FG)
    _level_row(draw, y + 188, "Gewinnmarge", _fig(m.profit_margin, pct=True), _FG)
    _level_row(draw, y + 242, "Fundamental-Score", f"{m.fund_score:.2f}", _LIGHT[level])

    _wrap(draw, c.fundamental_text, _font(36), 60, y + 350, 40, _FG, 48)
    return _save(img, out_path)


def render_overall_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    _card_header(draw, c, "3 · Gesamtbild", "3/3")

    o_level, o_label = ind.tendency(m.blended, "overall")
    _signal_badge(draw, 60, 420, o_level, f"Gesamtbild: {o_label}", big=True)

    # recap of the two dimensions as small lights
    y = 560
    draw.rounded_rectangle((60, y, W - 60, y + 200), radius=24, fill=_CARD)
    c_level, c_label = ind.tendency(m.tech_score, "chart")
    f_level, f_label = ind.tendency(m.fund_score, "fund")
    _signal_badge(draw, 90, y + 30, c_level, f"Charttechnik — {c_label}")
    _signal_badge(draw, 90, y + 110, f_level, f"Fundamental — {f_label}")

    _wrap(draw, c.overall_text, _font(38), 60, y + 260, 38, _FG, 50)
    return _save(img, out_path)


# ── Earnings + overview cards ──────────────────────────────────────────────
def render_earnings_card(items: list[EarningsItem], out_path: str, day_label: str) -> str:
    img, draw = _new_card()
    draw.text((60, 200), "Quartalszahlen heute", font=_font(64, bold=True), fill=_FG)
    draw.text((60, 290), day_label, font=_font(34), fill=_MUTED)

    y = 400
    if not items:
        draw.text((60, y), "Heute keine relevanten Termine.", font=_font(40), fill=_MUTED)
        return _save(img, out_path)

    for it in items[:14]:
        x = _market_badge(draw, 60, y, it.market)
        draw.text((x, y + 2), it.ticker, font=_font(40, bold=True), fill=_BRAND)
        draw.text((x + 190, y + 8), f"{it.name}"[:24], font=_font(32), fill=_FG)
        if it.when:
            draw.text((x, y + 50), it.when, font=_font(26), fill=_MUTED)
        y += 100
        if y > H - 220:
            break
    return _save(img, out_path)


def render_candidates_overview_card(candidates: list[Candidate], out_path: str) -> str:
    img, draw = _new_card()
    draw.text((60, 200), "Auf der Watchlist heute", font=_font(60, bold=True), fill=_FG)
    draw.text((60, 285), "Charttechnik + Fundamental · verschiedene Branchen",
              font=_font(32), fill=_MUTED)

    y = 400
    for c in candidates:
        m = c.metrics
        o_level, _ = ind.tendency(m.blended, "overall")
        # overall traffic light per ticker
        draw.ellipse((60, y + 6, 96, y + 42), fill=_LIGHT[o_level])
        x = _market_badge(draw, 116, y, m.market)
        draw.text((x, y + 2), m.ticker, font=_font(44, bold=True), fill=_FG)
        draw.text((x + 200, y + 8), f"{m.sector}"[:20], font=_font(30), fill=_MUTED)
        c_lvl, c_lab = ind.tendency(m.tech_score, "chart")
        f_lvl, f_lab = ind.tendency(m.fund_score, "fund")
        draw.text((116, y + 58), f"Chart: {c_lab}  ·  Fundamental: {f_lab}",
                  font=_font(28), fill=_MUTED)
        y += 138
        if y > H - 260:
            break
    return _save(img, out_path)
