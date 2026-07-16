"""Pexels stock-footage client: one portrait clip per script segment,
cached on disk. Returns None per segment when nothing usable is found —
the renderer then falls back to an animated gradient background."""
from pathlib import Path

import httpx
from loguru import logger

import config

_SEARCH_URL = "https://api.pexels.com/videos/search"


def _pick_file(video: dict) -> dict | None:
    """Best portrait file: HD-ish, smallest that still covers 1080×1920."""
    candidates = [
        f for f in video.get("video_files", [])
        if f.get("height") and f.get("width") and f["height"] > f["width"] and f["height"] >= 1280
    ]
    return min(candidates, key=lambda f: f["height"], default=None)


class PexelsBroll:
    def __init__(self):
        self.cache_dir = Path(config.BROLL_CACHE_DIR)

    def fetch(self, query: str, min_seconds: float) -> str | None:
        if not config.PEXELS_API_KEY or not query:
            return None
        try:
            response = httpx.get(
                _SEARCH_URL,
                headers={"Authorization": config.PEXELS_API_KEY},
                params={
                    "query": query,
                    "orientation": "portrait",
                    "size": "medium",
                    "per_page": 5,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            videos = response.json().get("videos", [])
        except Exception as exc:  # noqa: BLE001 — b-roll is optional, gradient fallback exists
            logger.warning(f"Pexels-Suche '{query}' fehlgeschlagen: {exc}")
            return None

        for video in videos:
            if video.get("duration", 0) < min_seconds:
                continue
            file = _pick_file(video)
            if not file:
                continue
            target = self.cache_dir / f"pexels_{video['id']}_{file['height']}.mp4"
            if target.exists():
                return str(target)
            try:
                data = httpx.get(file["link"], timeout=120.0, follow_redirects=True)
                data.raise_for_status()
                target.write_bytes(data.content)
                logger.info(f"B-Roll geladen: '{query}' → {target.name}")
                return str(target)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"B-Roll-Download fehlgeschlagen ({file['link']}): {exc}")
        return None
