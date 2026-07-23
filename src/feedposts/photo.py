"""Photo-based feed posts: a real topic photo as a full-bleed cover with a bold
headline overlay (magazine style), like image-heavy competitor posts. Photo source is
Pexels when PEXELS_API_KEY is set (clean commercial licence), else a keyless fallback
(Openverse) for previews. Falls back to a solid brand cover if no image is found."""
from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

import config
from src import branding

W, H = 1080, 1350


def fetch_photo(query: str, out_path: str) -> str | None:
    """Download one landscape/large topic photo → out_path. None on failure."""
    url = _pexels_photo(query) or _wikimedia_photo(query) or _openverse_photo(query)
    if not url:
        return None
    try:
        data = httpx.get(url, timeout=40.0, follow_redirects=True,
                         headers={"User-Agent": "renditeradar/1.0 (contact: renditeradar@instagram)"})
        data.raise_for_status()
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(data.content)
        return out_path
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Foto-Download fehlgeschlagen ({url}): {exc}")
        return None


def _pexels_photo(query: str) -> str | None:
    if not config.PEXELS_API_KEY:
        return None
    try:
        r = httpx.get("https://api.pexels.com/v1/search",
                      headers={"Authorization": config.PEXELS_API_KEY},
                      params={"query": query, "orientation": "portrait", "per_page": 5},
                      timeout=30.0)
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if photos:
            return photos[0]["src"].get("large2x") or photos[0]["src"].get("large")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Pexels-Foto '{query}' fehlgeschlagen: {exc}")
    return None


def _wikimedia_photo(query: str) -> str | None:
    """Keyless Wikimedia Commons search (PD/CC, commercial-friendly). Returns a scaled
    JPEG/PNG thumb URL. Reliable fallback when no Pexels key is set."""
    try:
        r = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params={"action": "query", "format": "json", "generator": "search",
                    "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6,
                    "gsrlimit": 12, "prop": "imageinfo", "iiprop": "url|mime|size",
                    "iiurlwidth": 1300},
            headers={"User-Agent": "renditeradar/1.0 (contact: renditeradar@instagram)"},
            timeout=30.0)
        r.raise_for_status()
        pages = (r.json().get("query") or {}).get("pages") or {}
        best = None
        for p in pages.values():
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("mime") not in ("image/jpeg", "image/png"):
                continue
            if (info.get("width") or 0) < 900:          # skip tiny/icon files
                continue
            url = info.get("thumburl") or info.get("url")
            if url:
                best = best or url
        return best
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Wikimedia-Foto '{query}' fehlgeschlagen: {exc}")
    return None


def _openverse_photo(query: str) -> str | None:
    """Keyless fallback for previews (CC-licensed; use Pexels for production)."""
    try:
        r = httpx.get("https://api.openverse.org/v1/images/",
                      params={"q": query, "size": "large", "license_type": "commercial",
                              "page_size": 5},
                      headers={"User-Agent": "renditeradar/1.0"}, timeout=30.0)
        r.raise_for_status()
        for item in r.json().get("results", []):
            if item.get("url"):
                return item["url"]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Openverse-Foto '{query}' fehlgeschlagen: {exc}")
    return None


def _cover_crop(img):
    from PIL import Image

    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def render_photo_cover(image_path: str | None, kicker: str, headline: str,
                       subline: str, out_path: str) -> str:
    """Full-bleed photo + dark gradient + kicker/headline/subline + brand tag."""
    from PIL import Image, ImageDraw

    if image_path and Path(image_path).exists():
        base = _cover_crop(Image.open(image_path).convert("RGB")).convert("RGBA")
    else:
        base = Image.new("RGBA", (W, H), branding.BG + (255,))

    # readability gradient: transparent at top → strong dark at the bottom
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        a = int(235 * (max(0, y - H * 0.30) / (H * 0.70)) ** 1.3)
        gd.line((0, y, W, y), fill=(6, 12, 18, min(a, 235)))
    base = Image.alpha_composite(base, grad)
    draw = ImageDraw.Draw(base)

    # brand tag top-left
    draw.text((60, 60), config.BRAND_NAME, font=branding.load_font(40, bold=True), fill=(255, 255, 255))
    if config.BRAND_HANDLE:
        draw.text((62, 112), config.BRAND_HANDLE, font=branding.load_font(26), fill=(220, 228, 235))

    # headline block, bottom-anchored
    h_lines = branding.wrap_lines(headline, 16)
    s_lines = branding.wrap_lines(subline, 30) if subline else []
    hf, sf = branding.load_font(84, bold=True), branding.load_font(38)
    block_h = len(h_lines) * 96 + (len(s_lines) * 50 + 24 if s_lines else 0)
    y = H - 150 - block_h
    if kicker:
        kf = branding.load_font(30, bold=True)
        kw = draw.textlength(kicker.upper(), font=kf)
        draw.rounded_rectangle((60, y - 66, 60 + kw + 44, y - 8), radius=12, fill=branding.BLUE)
        draw.text((82, y - 58), kicker.upper(), font=kf, fill=(255, 255, 255))
    y = branding.draw_lines(draw, h_lines, 60, y, hf, (255, 255, 255), 96)
    if s_lines:
        branding.draw_lines(draw, s_lines, 60, y + 24, sf, (225, 232, 238), 50)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, "JPEG", quality=90)
    return out_path
