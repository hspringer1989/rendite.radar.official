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
_TOP = 250          # start content below Instagram's profile-name overlay at the top
_MARGIN = 60        # left/right content margin (container spans 60 … W-60)
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

    # No brand header at the top: Instagram overlays the profile name (@rendite.radar.official)
    # there in stories, so a baked-in header would collide with it.
    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)
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


def _wrap_px(draw, text: str, font, x: int, y: int, right: int, fill, line_h: int,
             max_lines: int | None = None) -> int:
    """Wrap text to the FULL container width (x … right) by measuring pixels, so lines
    reach the right edge instead of breaking early (no ugly right-hand indent). With
    `max_lines`, extra text is trimmed and the last visible line ends with an ellipsis."""
    max_w = right - x
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if line and draw.textlength(trial, font=font) > max_w:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + " …", font=font) > max_w:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last + " …"
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def _center(draw, text: str, font, y: int, fill) -> None:
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)


def _center_wrap(draw, text: str, font, y: int, width_chars: int, fill, line_h: int) -> int:
    for line in branding.wrap_lines(text, width_chars):
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, y), line, font=font, fill=fill)
        y += line_h
    return y


def render_new_post_story(title: str, out_path: str, badge: str = "NEUER BEITRAG",
                          sub: str = "gerade im Feed erschienen",
                          cta: str = "Jetzt im Feed ansehen") -> str:
    """A striking announcement story for fresh content (feed carousel or reel).

    Graph-API stories can't carry a tappable link/sticker, so instead of a fake button
    we point users to the ONE tappable element Instagram itself provides: the profile
    name at the top of the story (tapping it opens the profile → the new content)."""
    img, draw = _new_card()
    draw.rounded_rectangle((80, 470, W - 80, 668), radius=54, fill=_BRAND)
    _center(draw, badge, _font(84, bold=True), 512, (255, 255, 255))
    _center(draw, sub, _font(40), 760, _MUTED)
    _center_wrap(draw, title, _font(58, bold=True), 860, 22, _FG, 76)

    _center(draw, cta, _font(46, bold=True), 1280, _BRAND)
    _center(draw, "tippe oben auf mein Profil", _font(34), 1352, _MUTED)
    return _save(img, out_path)


def _save(img, out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=90)
    return out_path




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


# ── Combined single analysis card (template "Story-Card-selection") ─────────
# Design: near-black page, two light cards (Fundamental figures + Charttechnik chart),
# a dark FAZIT strip with the overall traffic light. Everything on ONE story.
_PAGE = (10, 14, 22)          # near-black page background
_CARD_LT = (243, 241, 235)    # cream card
_TILE = (231, 229, 221)       # stat tile
_INK = (20, 26, 34)           # dark text on light card
_INK_MUT = (108, 118, 130)    # muted dark text
_CHIP = (24, 28, 36)          # dark number chip / fazit strip
_CHARTBG = (16, 22, 32)       # dark chart panel inside the light card


def _tint(color, amount: float = 0.82):
    """Light pastel tint of a signal colour (for the ZIEL/STOP value boxes)."""
    return tuple(int(c + (255 - c) * amount) for c in color)


def _ampel_pill(draw, right_x: int, y: int, level: str) -> None:
    """Dark rounded pill with three dots; the dot for `level` is lit in its signal colour."""
    w, h = 132, 54
    x = right_x - w
    draw.rounded_rectangle((x, y, x + w, y + h), radius=27, fill=_CHIP)
    colors = {"neg": _RED, "neu": _AMBER, "pos": _ACCENT}
    for i, lv in enumerate(("neg", "neu", "pos")):
        cx, cy = x + 30 + i * 36, y + h // 2
        col = colors[lv] if lv == level else (74, 82, 94)
        draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=col)


def _section_title(draw, x: int, y: int, num: str, title: str, level: str) -> None:
    draw.rounded_rectangle((x, y, x + 54, y + 54), radius=12, fill=_CHIP)
    draw.text((x + 15, y + 8), num, font=_font(30, bold=True), fill=(255, 255, 255))
    draw.text((x + 74, y + 6), title, font=_font(44, bold=True), fill=_INK)
    _ampel_pill(draw, W - 76, y, level)


def _stat_tile(draw, box, value: str, label: str) -> None:
    x0, y0, x1, _ = box
    draw.rounded_rectangle(box, radius=16, fill=_TILE)
    cx = (x0 + x1) // 2
    vf = _font(44, bold=True)
    draw.text((cx - draw.textlength(value, font=vf) / 2, y0 + 20), value, font=vf, fill=_INK)
    lf = _font(23)
    draw.text((cx - draw.textlength(label, font=lf) / 2, y0 + 80), label, font=lf, fill=_INK_MUT)


def _val_box(draw, x: int, y: int, label: str, value: str, color) -> None:
    w, h = 218, 122
    draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=_tint(color))
    draw.text((x + 20, y + 16), label, font=_font(24, bold=True), fill=color)
    draw.text((x + 20, y + 54), value, font=_font(42, bold=True), fill=color)


def _dashed_hline(draw, x0: int, x1: int, y: float, color, dash: int = 16, gap: int = 12) -> None:
    x = x0
    while x < x1:
        draw.line((x, y, min(x + dash, x1), y), fill=color, width=3)
        x += dash + gap


def _mini_chart(draw, box, m, c) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill=_CHARTBG)
    closes = m.history_closes
    if not closes or len(closes) < 2:
        draw.text((x0 + 24, y0 + 24), "Chartdaten n/a", font=_font(26), fill=_MUTED)
        return
    pad = 26
    ax0, ay0, ax1, ay1 = x0 + pad, y0 + pad + 6, x1 - pad, y1 - pad
    lo, hi = min(min(closes), c.stop_loss), max(max(closes), c.take_profit)
    if hi <= lo:
        hi = lo + 1.0
    def X(i): return ax0 + (ax1 - ax0) * i / (len(closes) - 1)
    def Y(v): return ay1 - (ay1 - ay0) * (v - lo) / (hi - lo)
    _dashed_hline(draw, ax0, ax1, Y(c.take_profit), _ACCENT)
    _dashed_hline(draw, ax0, ax1, Y(c.stop_loss), _RED)
    draw.text((ax0 + 2, Y(c.take_profit) - 30), "ZIEL", font=_font(22, bold=True), fill=_ACCENT)
    draw.text((ax0 + 2, Y(c.stop_loss) + 6), "STOP", font=_font(22, bold=True), fill=_RED)
    pts = [(X(i), Y(v)) for i, v in enumerate(closes)]
    draw.line(pts, fill=_BRAND, width=5)
    ex, ey = pts[-1]
    draw.ellipse((ex - 9, ey - 9, ex + 9, ey + 9), fill=(255, 255, 255))


def _wrap_lines_px(draw, text: str, font, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if line and draw.textlength(trial, font=font) > max_w:
                out.append(line)
                line = word
            else:
                line = trial
        if line:
            out.append(line)
    return out


def _draw_fit(draw, text: str, box, fill, size_max: int, size_min: int,
              bold: bool = False, ratio: float = 1.34) -> int:
    """Draw `text` wrapped inside `box` (x0,y0,x1,y1), shrinking the font from size_max
    down until ALL of it fits — so text is never cut off (no ellipsis)."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    font = _font(size_min, bold)
    lh = int(size_min * ratio)
    lines = _wrap_lines_px(draw, text, font, bw)
    for size in range(size_max, size_min - 1, -1):
        f = _font(size, bold)
        h = int(size * ratio)
        ls = _wrap_lines_px(draw, text, f, bw)
        if len(ls) * h <= bh:
            font, lh, lines = f, h, ls
            break
    else:
        lines = lines[: max(1, bh // lh)]  # pathological length only
    yy = y0
    for line in lines:
        draw.text((x0, yy), line, font=font, fill=fill)
        yy += lh
    return yy


_FAZIT_HEADING = {"pos": "Chancen überwiegen", "neu": "Ausgewogenes Bild", "neg": "Risiken überwiegen"}
_INK_SOFT = (66, 74, 86)      # dark body text on the light Fazit card
_HEAD_SUB = (224, 230, 238)   # near-white header subtitle (was grey)
_DOT_OFF_LT = (201, 205, 212)  # inactive traffic dot on a light background


def render_analysis_card(c: Candidate, out_path: str) -> str:
    """ONE story card with Fundamental + Charttechnik + Fazit (template design).
    Text boxes auto-shrink their font so nothing is ever cut off."""
    from PIL import Image, ImageDraw

    m = c.metrics
    img = Image.new("RGB", (W, H), _PAGE)
    draw = ImageDraw.Draw(img)
    y = _TOP

    # header: (trend badge) + ticker + name (subtitle in near-white, not grey)
    if c.category:
        w = draw.textlength(c.category, font=_font(26, bold=True))
        draw.rounded_rectangle((40, y, 40 + w + 40, y + 46), radius=12, fill=_BRAND)
        draw.text((60, y + 8), c.category, font=_font(26, bold=True), fill=(255, 255, 255))
        y += 60
    x = _market_badge(draw, 40, y + 10, m.market)
    draw.text((x, y), m.ticker, font=_font(54, bold=True), fill=_FG)
    draw.text((x, y + 62), f"{m.name} · {m.sector}"[:38], font=_font(26), fill=_HEAD_SUB)
    y += 122

    # ── Card 01 · Fundamental ────────────────────────────────────────────────
    f_lvl, _ = ind.tendency(m.fund_score, "fund")
    fh = 402
    draw.rounded_rectangle((40, y, W - 40, y + fh), radius=28, fill=_CARD_LT)
    _section_title(draw, 76, y + 30, "01", "Fundamental", f_lvl)
    tiles = [
        (_fig(m.pe), "KGV"),
        (f"{m.dividend_yield:.1f} %".replace(".", ",") if m.dividend_yield else "—", "Div.-Rendite"),
        (_fig(m.revenue_growth, pct=True), "Umsatz +"),
        (_fig(m.profit_margin, pct=True), "Marge"),
    ]
    tw, gap = 218, 14
    tx = 76
    for value, label in tiles:
        _stat_tile(draw, (tx, y + 108, tx + tw, y + 232), value, label)
        tx += tw + gap
    _draw_fit(draw, c.fundamental_text, (76, y + 250, W - 76, y + fh - 20), _INK, 32, 23)
    y += fh + 24

    # ── Card 02 · Charttechnik ───────────────────────────────────────────────
    c_lvl, _ = ind.tendency(m.tech_score, "chart")
    ch = 556
    draw.rounded_rectangle((40, y, W - 40, y + ch), radius=28, fill=_CARD_LT)
    _section_title(draw, 76, y + 30, "02", "Charttechnik", c_lvl)
    _mini_chart(draw, (76, y + 108, 748, y + 380), m, c)
    _val_box(draw, 782, y + 108, "ZIEL", f"{c.take_profit:.0f} {m.currency}", _ACCENT)
    _val_box(draw, 782, y + 258, "STOP", f"{c.stop_loss:.0f} {m.currency}", _RED)
    _draw_fit(draw, c.chart_text, (76, y + 398, W - 76, y + ch - 18), _INK, 32, 23)
    y += ch + 24

    # ── Fazit strip (light background, like the cards above) ─────────────────
    o_lvl, o_label = ind.tendency(m.blended, "overall")
    fzh = 300
    draw.rounded_rectangle((40, y, W - 40, y + fzh), radius=28, fill=_CARD_LT)
    draw.text((76, y + 40), "FAZIT", font=_font(26, bold=True), fill=_INK_MUT)
    for i, lv in enumerate(("neg", "neu", "pos")):
        cx = 76 + i * 46
        col = _LIGHT[lv] if lv == o_lvl else _DOT_OFF_LT
        draw.ellipse((cx, y + 92, cx + 32, y + 124), fill=col)
    draw.text((250, y + 36), f"Gesamtbild · {o_label}", font=_font(28, bold=True), fill=_INK_MUT)
    yy = _draw_fit(draw, _FAZIT_HEADING.get(o_lvl, "Ausgewogenes Bild"),
                   (250, y + 74, W - 76, y + 146), _INK, 46, 34, bold=True)
    body = f"Im Trend: {c.trend_reason}" if c.trend_reason else c.overall_text
    body_fill = _BRAND if c.trend_reason else _INK_SOFT
    _draw_fit(draw, body, (250, yy + 6, W - 76, y + fzh - 22), body_fill, 30, 22)

    draw.text((44, H - 62), "Keine Anlageberatung · keine Kauf-/Verkaufsempfehlung · Werbung",
              font=_font(24), fill=_MUTED)
    return _save(img, out_path)


# ── Candidate cards (3 per stock) ──────────────────────────────────────────
def _card_header(draw, c: Candidate, kind_label: str, step: str) -> int:
    """Prominent header below IG's profile overlay: optional TREND-AKTIE badge, a BIG
    card-type pill (instantly clear whether this is Charttechnik / Fundamental /
    Gesamtbild), then ticker + name. Returns the y to continue drawing at."""
    m = c.metrics
    y = _TOP
    if c.category:  # e.g. "TREND-AKTIE"
        w = draw.textlength(c.category, font=_font(26, bold=True))
        draw.rounded_rectangle((_MARGIN, y, _MARGIN + w + 40, y + 48), radius=12, fill=_BRAND)
        draw.text((_MARGIN + 20, y + 8), c.category, font=_font(26, bold=True), fill=(255, 255, 255))
        y += 66
    kf = _font(46, bold=True)
    kw = draw.textlength(kind_label, font=kf)
    draw.rounded_rectangle((_MARGIN, y, _MARGIN + kw + 56, y + 80), radius=18, fill=_BRAND)
    draw.text((_MARGIN + 28, y + 12), kind_label, font=kf, fill=(255, 255, 255))
    draw.text((W - 150, y + 24), step, font=_font(34, bold=True), fill=_MUTED)
    y += 104
    x = _market_badge(draw, _MARGIN, y + 12, m.market)
    draw.text((x, y), m.ticker, font=_font(58, bold=True), fill=_FG)
    y += 76
    draw.text((_MARGIN, y), f"{m.name}  ·  {m.sector}"[:44], font=_font(28), fill=_MUTED)
    return y + 62


def render_chart_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    y = _card_header(draw, c, "CHARTTECHNIK", "1/3")

    level, label = ind.tendency(m.tech_score, "chart")
    _signal_badge(draw, _MARGIN, y, level, f"Chart: {label}", big=True)
    ctop = y + 96
    _draw_chart(draw, (_MARGIN, ctop, W - _MARGIN, ctop + 430),
                m.history_closes, c.stop_loss, c.take_profit, c.entry, m.currency)

    # analysis text fills the full container width, between chart and the risk-marks box
    _wrap_px(draw, c.chart_text, _font(38), _MARGIN, ctop + 460, W - _MARGIN, _FG, 50)

    ry = 1474  # fixed so the box always clears the footer, whatever the text length
    draw.rounded_rectangle((_MARGIN, ry, W - _MARGIN, ry + 226), radius=24, fill=_CARD)
    draw.text((90, ry + 20), "Charttechnische Marken (keine Empfehlung)",
              font=_font(28, bold=True), fill=_MUTED)
    _level_row(draw, ry + 76, "Referenz (Schluss)", f"{c.entry:.2f} {m.currency}", _FG)
    _level_row(draw, ry + 128, "Risikomarke (Stop)", f"{c.stop_loss:.2f} {m.currency}", _RED)
    _level_row(draw, ry + 180, "Potenzialmarke (Ziel)", f"{c.take_profit:.2f} {m.currency}", _ACCENT)
    return _save(img, out_path)


def _fig(value, suffix="", pct=False):
    if value is None:
        return "n/a"
    if pct:
        return f"{value * 100:.0f} %"
    return f"{value:.1f}{suffix}".replace(".", ",")


def render_fundamental_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    y = _card_header(draw, c, "FUNDAMENTAL", "2/3")

    level, label = ind.tendency(m.fund_score, "fund")
    _signal_badge(draw, _MARGIN, y, level, f"Fundamental: {label}", big=True)

    y += 96
    draw.rounded_rectangle((_MARGIN, y, W - _MARGIN, y + 300), radius=24, fill=_CARD)
    draw.text((90, y + 22), "Kennzahlen (einfach erklärt)", font=_font(28, bold=True), fill=_MUTED)
    _level_row(draw, y + 80, "KGV (Preis je € Gewinn)", _fig(m.pe), _FG)
    _level_row(draw, y + 134, "Umsatzwachstum", _fig(m.revenue_growth, pct=True), _FG)
    _level_row(draw, y + 188, "Gewinnmarge", _fig(m.profit_margin, pct=True), _FG)
    _level_row(draw, y + 242, "Fundamental-Score", f"{m.fund_score:.2f}", _LIGHT[level])

    _wrap_px(draw, c.fundamental_text, _font(42), _MARGIN, y + 348, W - _MARGIN, _FG, 54)
    return _save(img, out_path)


def render_overall_card(c: Candidate, out_path: str) -> str:
    img, draw = _new_card()
    m = c.metrics
    y = _card_header(draw, c, "GESAMTBILD", "3/3")

    o_level, o_label = ind.tendency(m.blended, "overall")
    _signal_badge(draw, _MARGIN, y, o_level, f"Gesamtbild: {o_label}", big=True)

    # recap of the two dimensions as small lights
    y += 96
    draw.rounded_rectangle((_MARGIN, y, W - _MARGIN, y + 200), radius=24, fill=_CARD)
    c_level, c_label = ind.tendency(m.tech_score, "chart")
    f_level, f_label = ind.tendency(m.fund_score, "fund")
    _signal_badge(draw, 90, y + 30, c_level, f"Charttechnik — {c_label}")
    _signal_badge(draw, 90, y + 110, f_level, f"Fundamental — {f_label}")

    y += 260
    if c.trend_reason:
        y = _wrap_px(draw, f"Im Trend: {c.trend_reason}", _font(34), _MARGIN, y, W - _MARGIN, _BLUE, 46)
        y += 18
    _wrap_px(draw, c.overall_text, _font(44), _MARGIN, y, W - _MARGIN, _FG, 56)
    return _save(img, out_path)


# ── Earnings + overview cards (light "story" templates) ────────────────────
_LT_BG = (243, 241, 235)      # cream page
_LT_CARD = (255, 255, 255)    # white row card
_LT_INK = (22, 27, 32)        # dark text
_LT_GREY = (140, 148, 156)    # muted grey (sector, footer)
_LT_BADGE = (26, 28, 32)      # dark US/EU badge
_LT_PILL = (233, 231, 224)    # light grey pill (vorbörslich)
_LT_INFO = (230, 240, 251)    # light-blue info banner
_LT_TIMEBOX = (238, 234, 226)  # beige box behind the "ANALYSE IN MEINER STORY" time

# Trailing tokens dropped from a company name for a clean display label.
_NAME_DROP = {"AG", "SE", "N", "V", "NV", "SA", "S.A.", "PLC", "AB", "ASA", "OYJ", "SPA",
              "INC", "INC.", "CORP", "CORP.", "CORPORATION", "CO", "CO.", "COMPANY",
              "INTERNATIONAL", "COMMUNICATIONS", "HOLDING", "HOLDINGS", "GROUP",
              "ACT.A", "ACT", "A", "THE", "LTD", "LTD.", "LIMITED"}


def _clean_name(name: str) -> str:
    """Drop legal/share-class suffixes and de-shout ALL-CAPS names for a clean label
    (e.g. 'VOLKSWAGEN AG V' → 'Volkswagen', 'BNP PARIBAS ACT.A' → 'BNP Paribas')."""
    toks = name.replace(",", " ").split()
    while len(toks) > 1 and toks[-1].upper() in _NAME_DROP:
        toks.pop()
    if name.isupper():   # keep short acronyms upper (BNP), title-case the rest
        toks = [t if (len(t) <= 3 and t.isalpha()) else t.capitalize() for t in toks]
    return " ".join(toks)


def _truncate_px(draw, text: str, font, maxw: int) -> str:
    if draw.textlength(text, font=font) <= maxw:
        return text
    while text and draw.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text + "…" if text else text


def _brandmark(draw, x: int, y: int) -> None:
    """Small radar icon + 'RENDITE RADAR' wordmark (dark, on the light template)."""
    draw.ellipse((x, y, x + 50, y + 50), outline=_LT_INK, width=5)
    draw.ellipse((x + 30, y + 8, x + 46, y + 24), fill=_BRAND)
    draw.text((x + 70, y + 8), "RENDITE RADAR", font=_font(34, bold=True), fill=_LT_INK)


def _pill_right(draw, right_x: int, y: int, text: str, bg, fg, fsize: int = 28) -> int:
    f = _font(fsize, bold=True)
    w = draw.textlength(text, font=f)
    h = int(fsize * 1.85)
    x0 = int(right_x - w - 52)
    draw.rounded_rectangle((x0, y, right_x, y + h), radius=h // 2, fill=bg)
    draw.text((x0 + 26, y + int(h * 0.24)), text, font=f, fill=fg)
    return x0


def _dark_badge(draw, x: int, y: int, market: str) -> int:
    w, h = 76, 60
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=_LT_BADGE)
    t = market or "US"
    tf = _font(28, bold=True)
    draw.text((x + (w - draw.textlength(t, font=tf)) / 2, y + 14), t, font=tf, fill=(255, 255, 255))
    return x + w


def _lt_footer(draw) -> None:
    draw.text((44, H - 62), "Keine Anlageberatung · keine Kauf-/Verkaufsempfehlung · Werbung",
              font=_font(20), fill=_LT_GREY)
    hf = _font(22, bold=True)
    draw.text((W - 44 - draw.textlength(config.BRAND_HANDLE, font=hf), H - 63),
              config.BRAND_HANDLE, font=hf, fill=_LT_INK)


def _lt_head(draw, pill_text: str, title: str, sub_segments: list[tuple]) -> int:
    """Shared header: radar wordmark (left) + blue pill (right) + big title + subtitle.
    Fixed headline size so short titles stay on one line and long ones wrap (like the
    templates). Returns the y below the subtitle; kept clear of IG's top profile overlay."""
    _brandmark(draw, 60, 172)
    _pill_right(draw, W - 56, 170, pill_text, _BRAND, (255, 255, 255), 28)
    hf, lh, y = _font(76, bold=True), 88, 252
    for line in _wrap_lines_px(draw, title, hf, W - 130):
        draw.text((60, y), line, font=hf, fill=_LT_INK)
        y += lh
    x, sf = 62, _font(30, bold=True)
    for text, color in sub_segments:
        draw.text((x, y + 6), text, font=sf, fill=color)
        x += draw.textlength(text, font=sf)
    return y + 60


def render_earnings_card(items: list[EarningsItem], out_path: str, day_label: str) -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), _LT_BG)
    draw = ImageDraw.Draw(img)
    y = _lt_head(draw, "EARNINGS", "Quartalszahlen heute", [(day_label, _BRAND)]) + 20

    if not items:
        draw.text((60, y + 10), "Heute keine relevanten Termine.", font=_font(40), fill=_LT_GREY)
        _lt_footer(draw)
        return _save(img, out_path)

    nf = _font(46, bold=True)
    for it in items[:7]:
        lines = _wrap_lines_px(draw, _clean_name(it.name) or it.ticker, nf, 560)[:2]
        ch = 150 if len(lines) == 1 else 202
        draw.rounded_rectangle((60, y, W - 60, y + ch), radius=24, fill=_LT_CARD)
        draw.rounded_rectangle((62, y + 18, 74, y + ch - 18), radius=6, fill=_BRAND)   # accent bar
        bx = _dark_badge(draw, 104, y + ch // 2 - 30, it.market)
        tx = bx + 34
        block_h = len(lines) * 54 + 42
        ty = y + (ch - block_h) // 2
        for ln in lines:
            draw.text((tx, ty), ln, font=nf, fill=_LT_INK)
            ty += 54
        draw.text((tx, ty + 2), it.ticker, font=_font(30, bold=True), fill=_BRAND)
        if it.when:
            _pill_right(draw, W - 92, y + ch // 2 - 26, it.when, _LT_PILL, (108, 114, 122), 26)
        y += ch + 20
        if y > H - 220:
            break
    _lt_footer(draw)
    return _save(img, out_path)


def render_candidates_overview_card(candidates: list[Candidate], out_path: str) -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), _LT_BG)
    draw = ImageDraw.Draw(img)
    y = _lt_head(draw, "WATCHLIST", "Auf der Watchlist heute",
                 [("Charttechnik + Fundamental", _BRAND),
                  ("  ·  verschiedene Branchen", _LT_GREY)]) + 8

    # info banner: the detail analyses go live at the per-stock times shown on the right
    info = "Detailanalysen erscheinen heute zur angegebenen Uhrzeit in der Story"
    inf = _font(21, bold=True)
    bx1 = min(W - 60, 60 + int(draw.textlength(info, font=inf)) + 92)
    draw.rounded_rectangle((60, y, bx1, y + 58), radius=29, fill=_LT_INFO)
    draw.ellipse((90, y + 21, 104, y + 35), fill=_BRAND)
    draw.text((120, y + 16), info, font=inf, fill=_BRAND)
    y += 60 + 26

    # expected time each stock's detail-analysis story goes live (EU vs US posting slots,
    # in list order — matches how publish_next_candidate_group posts them)
    eu, us = list(config.STORY_SLOTS_EU), list(config.STORY_SLOTS_US)
    times: dict[int, str] = {}
    ei = ui = 0
    for c in candidates[:5]:
        if c.metrics.market == "EU":
            times[id(c)] = eu[min(ei, len(eu) - 1)] if eu else ""
            ei += 1
        else:
            times[id(c)] = us[min(ui, len(us) - 1)] if us else ""
            ui += 1

    nf, tkf, sf, lf = _font(42, bold=True), _font(27, bold=True), _font(26), _font(27, bold=True)
    for c in candidates[:5]:
        m = c.metrics
        ch = 196
        draw.rounded_rectangle((60, y, W - 60, y + ch), radius=28, fill=_LT_CARD)
        _dark_badge(draw, 92, y + ch // 2 - 30, m.market)   # badge vertically centered
        tx = 196
        name = _truncate_px(draw, _clean_name(m.name), nf, 360)
        w_name = draw.textlength(name, font=nf)
        w_tk = draw.textlength(m.ticker, font=tkf)
        w_sec = draw.textlength(m.sector, font=sf)
        c_lvl, c_lab = ind.tendency(m.tech_score, "chart")
        f_lvl, f_lab = ind.tendency(m.fund_score, "fund")
        inline = (w_name + 18 + w_tk + 22 + w_sec) <= (760 - tx)   # sector fits on the name line?

        if inline:
            ty = y + (ch - 96) // 2
            draw.text((tx, ty), name, font=nf, fill=_LT_INK)
            draw.text((tx + w_name + 18, ty + 12), m.ticker, font=tkf, fill=_BRAND)
            draw.text((tx + w_name + 18 + w_tk + 22, ty + 14), m.sector, font=sf, fill=_LT_GREY)
            ay = ty + 66
        else:
            ty = y + (ch - 130) // 2
            draw.text((tx, ty), name, font=nf, fill=_LT_INK)
            draw.text((tx + w_name + 18, ty + 12), m.ticker, font=tkf, fill=_BRAND)
            draw.text((tx, ty + 50), _truncate_px(draw, m.sector, sf, 520), font=sf, fill=_LT_GREY)
            ay = ty + 100
        draw.ellipse((tx, ay, tx + 20, ay + 20), fill=_LIGHT[c_lvl])
        draw.text((tx + 30, ay - 5), f"Chart: {c_lab}", font=lf, fill=_LT_INK)
        x2 = tx + 30 + draw.textlength(f"Chart: {c_lab}", font=lf) + 40
        draw.ellipse((x2, ay, x2 + 20, ay + 20), fill=_LIGHT[f_lvl])
        draw.text((x2 + 30, ay - 5), f"Fundamental: {f_lab}", font=lf, fill=_LT_INK)

        # right time box: light beige rounded box with "ANALYSE IN MEINER STORY" + big time
        t = times.get(id(c), "")
        if t:
            bx0, bx1 = 788, W - 88
            draw.rounded_rectangle((bx0, y + 28, bx1, y + ch - 28), radius=18, fill=_LT_TIMEBOX)
            cx = (bx0 + bx1) // 2
            llf = _font(19, bold=True)
            for i, ln in enumerate(("ANALYSE IN", "MEINER STORY")):
                draw.text((cx - draw.textlength(ln, font=llf) / 2, y + 52 + i * 24),
                          ln, font=llf, fill=_LT_GREY)
            tf = _font(48, bold=True)
            draw.text((cx - draw.textlength(t, font=tf) / 2, y + 112), t, font=tf, fill=_BRAND)
        y += ch + 20
        if y > H - 210:
            break
    _lt_footer(draw)
    return _save(img, out_path)
