"""Central configuration, loaded from .env (same pattern as trading-bot)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_list(name: str, default: str = "") -> list[str]:
    raw = _get(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── Claude ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-sonnet-4-6")
CLAUDE_MODEL_FAST = _get("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
CLAUDE_DAILY_BUDGET_EUR = float(_get("CLAUDE_DAILY_BUDGET_EUR", "2.0"))
LLM_PROVIDER = _get("LLM_PROVIDER", "claude")  # claude | fake

# ── TTS ───────────────────────────────────────────────────────────────────
TTS_PROVIDER = _get("TTS_PROVIDER", "fake")  # elevenlabs | fake
ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = _get("ELEVENLABS_VOICE_ID")
ELEVENLABS_MODEL = _get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
TTS_DAILY_BUDGET_CHARS = int(_get("TTS_DAILY_BUDGET_CHARS", "15000"))

# ── Trend collectors ──────────────────────────────────────────────────────
REDDIT_CLIENT_ID = _get("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = _get("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = _get("REDDIT_USER_AGENT", "reel-autopilot/0.1")
REDDIT_SUBREDDITS = _get_list("REDDIT_SUBREDDITS", "Finanzen,mauerstrassenwetten,Aktien")
RSS_FEEDS = _get_list(
    "RSS_FEEDS",
    "https://www.tagesschau.de/wirtschaft/index~rss2.xml,"
    "https://www.n-tv.de/wirtschaft/rss,"
    "https://www.finanzen.net/rss/news",
)
GOOGLE_TRENDS_GEO = _get("GOOGLE_TRENDS_GEO", "DE")

# ── B-roll footage ────────────────────────────────────────────────────────
PEXELS_API_KEY = _get("PEXELS_API_KEY")

# ── Rendering ─────────────────────────────────────────────────────────────
FFMPEG_BIN = _get("FFMPEG_BIN", "ffmpeg")
REEL_WIDTH = 1080
REEL_HEIGHT = 1920
REEL_TARGET_SECONDS = int(_get("REEL_TARGET_SECONDS", "45"))
MUSIC_DIR = BASE_DIR / "assets" / "music"
MUSIC_VOLUME_DB = float(_get("MUSIC_VOLUME_DB", "-18"))

# ── Review via Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# ── Instagram publishing (Phase 2) ────────────────────────────────────────
IG_ACCESS_TOKEN = _get("IG_ACCESS_TOKEN")
IG_USER_ID = _get("IG_USER_ID")
FB_APP_ID = _get("FB_APP_ID")
FB_APP_SECRET = _get("FB_APP_SECRET")
GRAPH_API_VERSION = _get("GRAPH_API_VERSION", "v23.0")
PUBLIC_MEDIA_BASE_URL = _get("PUBLIC_MEDIA_BASE_URL").rstrip("/")
PUBLIC_MEDIA_DIR = _get("PUBLIC_MEDIA_DIR")
POSTING_SLOTS = _get_list("POSTING_SLOTS", "08:00,12:30,18:00")
TIMEZONE = _get("TIMEZONE", "Europe/Berlin")

# ── Branding ──────────────────────────────────────────────────────────────
BRAND_NAME = _get("BRAND_NAME", "Depotdenker")

# ── Pipeline ──────────────────────────────────────────────────────────────
MIN_TREND_SCORE = float(_get("MIN_TREND_SCORE", "0.65"))
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "reels"
BROLL_CACHE_DIR = DATA_DIR / "broll"
DB_PATH = DATA_DIR / "reel_autopilot.db"

for _d in (DATA_DIR, OUTPUT_DIR, BROLL_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
