"""Renders 1080×1920 Instagram-story cards with Pillow. Story stickers/links are
NOT available via the Graph API, so every bit of text (incl. the disclaimer and the
chart-derived risk marks) is baked into the image. Pillow is imported lazily so the
rest of the pipeline imports without it."""
from __future__ import annotations

import textwrap
from pathlib import Path

import config
from src.models import Candidate, EarningsItem

W, H = 1080, 1920
_BG = (14, 18, 28)          # near-black finance dark
_ACCENT = (34, 197, 94)     # green
_ACCENT_RED = (239, 68, 68)
_FG = (235, 238, 242)
_MUTED = (148, 163, 184)
_CARD = (24, 30, 44)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    # Try a few fonts that exist on Windows / most Linux boxes, else the PIL default.
    candidates = (
        ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _new_card():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)
    # Brand header (+ handle) + disclaimer footer are on every card.
    draw.text((60, 66), config.BRAND_NAME, font=_font(52, bold=True), fill=_ACCENT)
    if config.BRAND_HANDLE:
        draw.text((62, 128), config.BRAND_HANDLE, font=_font(28), fill=_MUTED)
    _footer(draw)
    return img, draw


def _footer(draw) -> None:
    # No emoji here: the bundled fonts have no emoji glyphs → they'd render as tofu.
    disclaimer = "Keine Anlageberatung  ·  nur Bildung & Unterhaltung  ·  Werbung"
    draw.line((60, H - 150, W - 60, H - 150), fill=_MUTED, width=2)
    draw.text((60, H - 130), disclaimer, font=_font(28), fill=_MUTED)


def _market_badge(draw, x: int, y: int, market: str) -> int:
    """Draw a small US/EU pill and return the x just past it."""
    color = _ACCENT if market == "US" else (96, 165, 250)  # green US / blue EU
    label = market or "US"
    w = 78
    draw.rounded_rectangle((x, y, x + w, y + 46), radius=12, outline=color, width=3)
    draw.text((x + 16, y + 6), label, font=_font(28, bold=True), fill=color)
    return x + w + 20


def _wrap(draw, text: str, font, x: int, y: int, width_chars: int, fill, line_h: int) -> int:
    for line in textwrap.wrap(text, width=width_chars) or [""]:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def _save(img, out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
    return out_path


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
        when = f"  ·  {it.when}" if it.when else ""
        draw.text((x, y + 2), it.ticker, font=_font(40, bold=True), fill=_ACCENT)
        draw.text((x + 190, y + 8), f"{it.name}"[:24], font=_font(32), fill=_FG)
        if when:
            draw.text((x, y + 50), when.strip(), font=_font(26), fill=_MUTED)
        y += 100
        if y > H - 220:
            break
    return _save(img, out_path)


def _level_row(draw, y: int, label: str, value: str, color) -> None:
    draw.text((90, y), label, font=_font(32), fill=_MUTED)
    draw.text((520, y), value, font=_font(34, bold=True), fill=color)


def render_candidate_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    x = _market_badge(draw, 60, 214, m.market)
    draw.text((x, 190), m.ticker, font=_font(72, bold=True), fill=_FG)
    draw.text((60, 300), f"{m.name}  ·  {m.sector}", font=_font(34), fill=_MUTED)

    # Score bar-ish summary
    draw.text((60, 380), f"Charttechnik {m.tech_score:.2f}   Fundamental {m.fund_score:.2f}",
              font=_font(34), fill=_ACCENT)

    # Educational analysis text
    y = _wrap(draw, c.analysis, _font(36), 60, 470, 40, _FG, 48)

    # Chart-derived risk marks (framed as marks, not advice)
    y = max(y + 40, 1180)
    from PIL import ImageDraw  # noqa: F401 (kept explicit for clarity)
    draw.rounded_rectangle((60, y, W - 60, y + 340), radius=24, fill=_CARD)
    draw.text((90, y + 24), "Charttechnische Marken (keine Empfehlung)",
              font=_font(30, bold=True), fill=_MUTED)
    cur = m.currency
    _level_row(draw, y + 90, "Referenz (Schluss)", f"{c.entry:.2f} {cur}", _FG)
    _level_row(draw, y + 150, "Risikomarke (Stop)", f"{c.stop_loss:.2f} {cur}", _ACCENT_RED)
    _level_row(draw, y + 210, "Potenzialmarke (Ziel)", f"{c.take_profit:.2f} {cur}", _ACCENT)
    _level_row(draw, y + 270, "RSI / ATR", f"{m.rsi:.0f} / {m.atr:.2f}", _MUTED)
    return _save(img, out_path)


def render_candidates_overview_card(candidates: list[Candidate], out_path: str) -> str:
    img, draw = _new_card()
    draw.text((60, 200), "Auf der Watchlist heute", font=_font(60, bold=True), fill=_FG)
    draw.text((60, 285), "Charttechnik + Fundamental · verschiedene Branchen",
              font=_font(32), fill=_MUTED)

    y = 400
    for c in candidates:
        m = c.metrics
        x = _market_badge(draw, 60, y, m.market)
        draw.text((x, y + 2), m.ticker, font=_font(44, bold=True), fill=_ACCENT)
        draw.text((x + 200, y + 8), f"{m.sector}"[:22], font=_font(32), fill=_FG)
        draw.text((60, y + 60),
                  f"Chart {m.tech_score:.2f}  ·  Fund {m.fund_score:.2f}  ·  RSI {m.rsi:.0f}",
                  font=_font(28), fill=_MUTED)
        y += 138
        if y > H - 260:
            break
    return _save(img, out_path)
