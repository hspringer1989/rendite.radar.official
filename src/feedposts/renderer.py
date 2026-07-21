"""Renders a FeedPost to 1080×1350 carousel slides on the brand templates.

- Hook (first) and CTA (last) slide → blue radar template with a dark readability panel.
- Content slides → dark template; heading (blue) + body (white) in a safe left column
  that clears the top-right logo and the bottom chart motif.
Pillow is imported lazily so importing this module never requires it."""
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


def _render_hero(slide: Slide, index: int, total: int, is_cta: bool, out_path: str) -> str:
    from PIL import ImageDraw

    base = _panel(_open_bg(config.FEED_TEMPLATE_TITLE), (60, 300, W - 60, 1040), alpha=205)
    draw = ImageDraw.Draw(base)
    _counter(draw, index, total)

    y = branding.wrap(draw, slide.heading, branding.load_font(60, bold=True),
                      100, 360, 22, branding.FG, 74)
    y = branding.wrap(draw, slide.body, branding.load_font(40),
                      100, y + 30, 30, branding.FG, 54)
    if is_cta:
        draw.text((100, 960), f"⚠️ {_CTA_DISCLAIMER}"[:60], font=branding.load_font(24),
                  fill=branding.MUTED)
    return _save(base, out_path)


def _render_content(slide: Slide, index: int, total: int, out_path: str) -> str:
    from PIL import ImageDraw

    base = _open_bg(config.FEED_TEMPLATE_CONTENT)
    draw = ImageDraw.Draw(base)
    _counter(draw, index, total)

    y = branding.wrap(draw, slide.heading, branding.load_font(52, bold=True),
                      70, 200, 24, branding.BLUE, 64)
    branding.wrap(draw, slide.body, branding.load_font(40),
                  70, y + 30, 34, branding.FG, 54)
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
