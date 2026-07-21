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
# "Instagram API with Instagram Login" (creator account, no Facebook page):
#   https://graph.instagram.com — the default and recommended path.
# Classic Facebook-Login variant: https://graph.facebook.com
GRAPH_BASE_URL = _get("GRAPH_BASE_URL", "https://graph.instagram.com").rstrip("/")
PUBLIC_MEDIA_BASE_URL = _get("PUBLIC_MEDIA_BASE_URL").rstrip("/")
PUBLIC_MEDIA_DIR = _get("PUBLIC_MEDIA_DIR")
POSTING_SLOTS = _get_list("POSTING_SLOTS", "08:00,12:30,18:00")
TIMEZONE = _get("TIMEZONE", "Europe/Berlin")

# ── Branding ──────────────────────────────────────────────────────────────
# Display name + IG handle of the actually connected account (@rendite.radar.official,
# verified via `main.py verify-ig`). Keep these aligned with the real account.
BRAND_NAME = _get("BRAND_NAME", "Renditeradar")
BRAND_HANDLE = _get("BRAND_HANDLE", "@rendite.radar.official")

# ── Stocks / daily story pipeline ─────────────────────────────────────────
# yfinance | fake  (fake = offline testing without network)
STOCK_DATA_PROVIDER = _get("STOCK_DATA_PROVIDER", "yfinance")
# Ticker universe scanned for both the earnings card and the watchlist candidates.
# Mix US + EU (EU tickers carry an exchange suffix, e.g. SAP.DE).
STOCK_UNIVERSE = _get_list(
    "STOCK_UNIVERSE",
    # ~90 US + EU large/mid caps so the 30-day per-ticker cooldown never runs dry.
    # US:
    "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,BRK-B,JPM,V,MA,JNJ,WMT,PG,HD,XOM,CVX,"
    "KO,PEP,ABBV,MRK,PFE,LLY,BAC,WFC,GS,MS,C,AXP,DIS,NFLX,ADBE,CRM,ORCL,CSCO,"
    "INTC,AMD,QCOM,TXN,AVGO,IBM,GE,CAT,BA,HON,UNH,CVS,T,VZ,CMCSA,NKE,MCD,SBUX,"
    "COST,TGT,"
    # EU (yfinance exchange suffixes):
    "SAP.DE,SIE.DE,ALV.DE,DTE.DE,AIR.DE,BAS.DE,BAYN.DE,BMW.DE,MBG.DE,VOW3.DE,"
    "DBK.DE,IFX.DE,ADS.DE,MUV2.DE,RWE.DE,ASML.AS,HEIA.AS,PRX.AS,MC.PA,OR.PA,"
    "RMS.PA,AI.PA,SU.PA,TTE.PA,SAN.PA,BNP.PA,NESN.SW,NOVN.SW,ROG.SW,UBSG.SW,"
    "ISP.MI,ENI.MI,ENEL.MI,SHEL.L,AZN.L,HSBA.L,ULVR.L,BP.L",
)
STOCK_CANDIDATES_COUNT = int(_get("STOCK_CANDIDATES_COUNT", "4"))
# A ticker analysed as a candidate is not picked again for this many days.
STOCK_REPEAT_COOLDOWN_DAYS = int(_get("STOCK_REPEAT_COOLDOWN_DAYS", "30"))
# Daily news-driven "Trend-Aktie" story (one stock most in the news, same cooldown pool).
STOCK_TREND_ENABLED = _get("STOCK_TREND_ENABLED", "true").lower() == "true"
# Blended factor weights (no sentiment): tech + fund should sum to 1.0.
STOCK_W_TECH = float(_get("STOCK_W_TECH", "0.5"))
STOCK_W_FUND = float(_get("STOCK_W_FUND", "0.5"))
# Chart-derived risk marks (ATR multiples), same convention as the trading-bot.
STOCK_ATR_STOP_MULT = float(_get("STOCK_ATR_STOP_MULT", "2.0"))
STOCK_ATR_TP_MULT = float(_get("STOCK_ATR_TP_MULT", "4.0"))
# When to build the daily earnings + watchlist stories (local TIMEZONE).
STOCK_STORY_SLOT = _get("STOCK_STORY_SLOT", "09:00")

# ── Feed posts (educational carousels, 2×/week) ────────────────────────────
# Posting slots as "<WEEKDAY> HH:MM" (MON..SUN, local TIMEZONE).
FEED_POST_SLOTS = _get_list("FEED_POST_SLOTS", "TUE 17:00,THU 17:00")
FEED_TEMPLATE_TITLE = BASE_DIR / "assets" / "templates" / "feed_bg_title.png"
FEED_TEMPLATE_CONTENT = BASE_DIR / "assets" / "templates" / "feed_bg_content.png"
# Auto-post a "New Post" announcement story whenever a feed carousel is published.
FEED_ANNOUNCE_STORY = _get("FEED_ANNOUNCE_STORY", "true").lower() == "true"
# Story POSTING slots (local TIMEZONE). Earnings + watchlist-overview go out in the
# morning; candidate cards are spread over the day at their market's trading hours
# (US cash session ≈ 15:30–22:00 Berlin, EU ≈ 09:00–17:30 Berlin). One story per slot.
STORY_POST_EARNINGS_SLOT = _get("STORY_POST_EARNINGS_SLOT", "09:30")
STORY_SLOTS_EU = _get_list("STORY_SLOTS_EU", "10:30,13:00,15:00")
STORY_SLOTS_US = _get_list("STORY_SLOTS_US", "16:00,18:30,20:30")

# ── Pipeline ──────────────────────────────────────────────────────────────
MIN_TREND_SCORE = float(_get("MIN_TREND_SCORE", "0.65"))
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "reels"
STORY_DIR = DATA_DIR / "stories"
FEED_DIR = DATA_DIR / "feed"
BROLL_CACHE_DIR = DATA_DIR / "broll"
DB_PATH = DATA_DIR / "reel_autopilot.db"

for _d in (DATA_DIR, OUTPUT_DIR, STORY_DIR, FEED_DIR, BROLL_CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
