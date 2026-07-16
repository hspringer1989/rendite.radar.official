"""Instagram Graph API publisher (Phase 2).

Flow: stage the MP4 under a public URL (nginx serves PUBLIC_MEDIA_DIR) →
create a REELS media container → poll until FINISHED → media_publish →
delete the staged file. Well under the 25-posts/24h API limit at 1–3 posts/day.
"""
import asyncio
import secrets
import shutil
from pathlib import Path

import httpx
from loguru import logger

import config

_GRAPH = "https://graph.facebook.com"
_POLL_INTERVAL_S = 10
_POLL_MAX_TRIES = 60  # ≈10 min of server-side video processing


class PublishError(RuntimeError):
    pass


def publishing_configured() -> bool:
    return bool(
        config.IG_ACCESS_TOKEN and config.IG_USER_ID
        and config.PUBLIC_MEDIA_BASE_URL and config.PUBLIC_MEDIA_DIR
    )


def _stage_video(video_path: str) -> tuple[Path, str]:
    """Copy the reel to the public media dir under a random, unguessable name."""
    name = f"{secrets.token_urlsafe(16)}.mp4"
    staged = Path(config.PUBLIC_MEDIA_DIR) / name
    staged.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video_path, staged)
    return staged, f"{config.PUBLIC_MEDIA_BASE_URL}/{name}"


async def publish_reel(video_path: str, caption: str) -> str:
    """Publish and return the IG media id. Raises PublishError on failure."""
    if not publishing_configured():
        raise PublishError("Instagram-Publishing ist nicht konfiguriert (.env)")

    staged, video_url = _stage_video(video_path)
    base = f"{_GRAPH}/{config.GRAPH_API_VERSION}/{config.IG_USER_ID}"
    token = {"access_token": config.IG_ACCESS_TOKEN}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{base}/media", data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
                "share_to_feed": "true",
                **token,
            })
            body = response.json()
            if "id" not in body:
                raise PublishError(f"Container-Erstellung fehlgeschlagen: {body}")
            container_id = body["id"]

            for _ in range(_POLL_MAX_TRIES):
                status = (await client.get(
                    f"{_GRAPH}/{config.GRAPH_API_VERSION}/{container_id}",
                    params={"fields": "status_code", **token},
                )).json().get("status_code")
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    raise PublishError("Instagram meldet Verarbeitungsfehler (status ERROR)")
                await asyncio.sleep(_POLL_INTERVAL_S)
            else:
                raise PublishError("Timeout: Container wurde nicht FINISHED")

            response = await client.post(f"{base}/media_publish", data={
                "creation_id": container_id, **token,
            })
            body = response.json()
            if "id" not in body:
                raise PublishError(f"media_publish fehlgeschlagen: {body}")
            media_id = body["id"]
    finally:
        staged.unlink(missing_ok=True)  # public exposure only as long as needed

    logger.info(f"Reel veröffentlicht: IG media id {media_id}")
    return media_id


async def fetch_insights(media_id: str) -> dict[str, int]:
    """Daily metrics for a published reel; empty dict on API errors."""
    metrics = "views,reach,likes,comments,saved,shares"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_GRAPH}/{config.GRAPH_API_VERSION}/{media_id}/insights",
            params={"metric": metrics, "access_token": config.IG_ACCESS_TOKEN},
        )
        body = response.json()
    if "data" not in body:
        logger.warning(f"Insights für {media_id} fehlgeschlagen: {body}")
        return {}
    result: dict[str, int] = {}
    for entry in body["data"]:
        values = entry.get("values") or [{}]
        result[entry["name"]] = int(values[0].get("value") or 0)
    return result


async def refresh_long_lived_token() -> str | None:
    """Exchange the current token for a fresh 60-day one (call e.g. weekly).
    Returns the new token — persisting it into .env is up to the caller."""
    if not (config.FB_APP_ID and config.FB_APP_SECRET):
        return None
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{_GRAPH}/{config.GRAPH_API_VERSION}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": config.FB_APP_ID,
            "client_secret": config.FB_APP_SECRET,
            "fb_exchange_token": config.IG_ACCESS_TOKEN,
        })
    body = response.json()
    return body.get("access_token")
