"""Renders a FeedPost to 1080×1350 carousel slides on the blue radar brand template.

Every slide uses the same blue radar background (config.FEED_TEMPLATE_TITLE) with a dark
readability panel behind the text, so the template's decorative blips never hide the
heading. Hook (first) + CTA (last) get a centred panel; the CTA adds a "JETZT FOLGEN"
button. Pillow is imported lazily so importing this module never requires it."""
from __future__ import annotations

from pathlib import Path

import config
from src import branding
from src.models import FeedPost, Slide

W, H = 1080, 1350
_CTA_DISCLAIMER = "Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung"


def _open_bg(path) -> "object":
    from PIL import Image

    if Path(path).exists():
        return Image.open(path).convert("RGBA").resize((W, H))
    # Fallback: solid brand-dark background if a template is missing.
    return Image.new("RGBA", (W, H), branding.BG + (255,))


def _panel(base, box, alpha: int = 200):
    """Composite a dark rounded panel onto an RGBA base for text readability."""
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, radius=30, fill=(10, 16, 22, alpha))
    return Image.alpha_composite(base, overlay)


def _save(base, out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path


def _counter(draw, index: int, total: int) -> None:
    draw.text((70, 66), f"{index + 1} / {total}", font=branding.load_font(30, bold=True),
              fill=branding.BLUE)


def _follow_button(draw, x: int, y: int) -> int:
    """Punchy blue 'FOLGEN' pill + handle to make the call-to-action pop."""
    label = "JETZT FOLGEN  »"
    font = branding.load_font(42, bold=True)
    pill = (x, y, x + 560, y + 92)
    draw.rounded_rectangle(pill, radius=46, fill=branding.BLUE)
    draw.text((x + 40, y + 22), label, font=font, fill=(255, 255, 255))
    draw.text((x + 6, y + 116), config.BRAND_HANDLE, font=branding.load_font(36, bold=True),
              fill=branding.BLUE_LIGHT)
    return y + 92 + 116


def _render_hero(slide: Slide, index: int, total: int, is_cta: bool, out_path: str) -> str:
    from PIL import ImageDraw

    h_font = branding.load_font(54, bold=True)
    b_font = branding.load_font(36)
    h_lines = branding.wrap_lines(slide.heading, 24)
    b_lines = branding.wrap_lines(slide.body, 34)
    h_lh, b_lh = 66, 48

    pad = 56
    content_h = len(h_lines) * h_lh + 22 + len(b_lines) * b_lh
    if is_cta:
        content_h += 40 + 208 + 34    # follow button + handle + disclaimer
    panel_h = content_h + 2 * pad
    top, bottom = 165, H - 175                   # keep clear of counter + template logo
    avail = bottom - top
    y0 = top + (avail - panel_h) // 2 if panel_h <= avail else top   # centre, else top-anchor
    y1 = y0 + panel_h

    base = _panel(_open_bg(config.FEED_TEMPLATE_TITLE), (60, y0, W - 60, y1), alpha=215)
    draw = ImageDraw.Draw(base)
    _counter(draw, index, total)

    x = 100
    y = branding.draw_lines(draw, h_lines, x, y0 + pad, h_font,
                            branding.BLUE if is_cta else branding.FG, h_lh)
    y = branding.draw_lines(draw, b_lines, x, y + 22, b_font, branding.FG, b_lh)
    if is_cta:
        y = _follow_button(draw, x, y + 40)
        draw.text((x, y + 8), _CTA_DISCLAIMER, font=branding.load_font(22), fill=branding.MUTED)
    return _save(base, out_path)


def _render_content(slide: Slide, index: int, total: int, out_path: str) -> str:
    from PIL import ImageDraw

    h_font = branding.load_font(52, bold=True)
    b_font = branding.load_font(40)
    h_lines = branding.wrap_lines(slide.heading, 24)
    b_lines = branding.wrap_lines(slide.body, 34)

    # All slides share the blue radar background; a dark panel behind the text keeps it
    # readable and hides the template's decorative dots/blips.
    y0, pad = 175, 46
    content_h = len(h_lines) * 64 + 26 + len(b_lines) * 54
    base = _panel(_open_bg(config.FEED_TEMPLATE_TITLE),
                  (50, y0 - pad, W - 50, y0 + content_h + pad), alpha=210)
    draw = ImageDraw.Draw(base)
    _counter(draw, index, total)

    y = branding.draw_lines(draw, h_lines, 90, y0, h_font, branding.BLUE, 64)
    branding.draw_lines(draw, b_lines, 90, y + 26, b_font, branding.FG, 54)
    return _save(base, out_path)


def render_feed_slides(post: FeedPost, out_dir: str, stamp: str) -> list[str]:
    """Render all slides; returns the image paths in carousel order."""
    out = Path(out_dir)
    total = len(post.slides)
    paths: list[str] = []
    for i, slide in enumerate(post.slides):
        target = str(out / f"feed_{post.topic_slug}_{i + 1}_{stamp}.jpg")
        is_hook = i == 0
        is_cta = i == total - 1 and total > 1
        if is_hook or is_cta:
            paths.append(_render_hero(slide, i, total, is_cta, target))
        else:
            paths.append(_render_content(slide, i, total, target))
    return paths
