"""Shared Renditeradar brand palette + Pillow helpers for story cards and feed posts.

Brand look (from the Claude-Design templates in assets/templates/): blue accent
(#2386D1) on a dark background, white text. Traffic-light colours (green/amber/red)
stay reserved for the SIGNAL meaning (bullish/neutral/bearish) and are not the brand
accent."""
from __future__ import annotations

import textwrap

# ── Brand palette ──────────────────────────────────────────────────────────
BLUE = (35, 134, 209)        # #2386D1 — primary brand accent (headers, badges, lines)
BLUE_LIGHT = (125, 185, 232)  # secondary blue (EU badge, SMA overlay)
BLUE_DEEP = (6, 74, 126)
BG = (24, 38, 30)            # dark template background tone
CARD = (34, 50, 44)          # slightly lifted panel
FG = (238, 242, 245)
MUTED = (150, 165, 175)

# ── Traffic-light (semantic signal, NOT brand accent) ──────────────────────
GREEN = (34, 197, 94)
AMBER = (234, 179, 8)
RED = (239, 68, 68)
LIGHT = {"pos": GREEN, "neu": AMBER, "neg": RED}


def load_font(size: int, bold: bool = False):
    from PIL import ImageFont

    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_lines(text: str, width_chars: int) -> list[str]:
    """Wrap text to lines (honouring explicit newlines) without drawing — for measuring."""
    lines: list[str] = []
    for para in text.split("\n"):
        lines.extend(textwrap.wrap(para, width=width_chars) or [""])
    return lines


def draw_lines(draw, lines: list[str], x: int, y: int, font, fill, line_h: int) -> int:
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def wrap(draw, text: str, font, x: int, y: int, width_chars: int, fill, line_h: int) -> int:
    """Draw wrapped text, honouring explicit newlines. Returns the y after the block."""
    return draw_lines(draw, wrap_lines(text, width_chars), x, y, font, fill, line_h)


def market_badge(draw, x: int, y: int, market: str) -> int:
    """Blue-family US/EU pill (kept off the green/amber/red signal palette)."""
    color = BLUE_LIGHT if market == "EU" else BLUE
    draw.rounded_rectangle((x, y, x + 78, y + 46), radius=12, outline=color, width=3)
    draw.text((x + 16, y + 6), market or "US", font=load_font(28, bold=True), fill=color)
    return x + 98
