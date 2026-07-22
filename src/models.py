"""Shared dataclasses passed between pipeline stages."""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TrendItem:
    """A candidate topic found by a collector."""
    source: str          # google_trends | reddit | rss
    title: str
    summary: str = ""
    url: str = ""
    popularity: float = 0.0  # source-native popularity hint (upvotes, rank, …)
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def uid(self) -> str:
        """Stable dedup key across runs."""
        return hashlib.sha256(f"{self.source}:{self.title.lower()}".encode()).hexdigest()[:32]


@dataclass
class TrendScore:
    viral_potential: float   # 0–1: hook/emotion/shareability of the topic
    niche_fit: float         # 0–1: fit for a German finance/investing profile
    monetization: float      # 0–1: proximity to broker/finance affiliate offers
    reasoning: str = ""

    @property
    def total(self) -> float:
        return round(
            0.45 * self.viral_potential + 0.30 * self.niche_fit + 0.25 * self.monetization, 4
        )


@dataclass
class ScriptSegment:
    text: str                # German voiceover text for this segment
    broll_query: str         # English search keywords for stock footage


@dataclass
class ReelScript:
    hook: str                          # first spoken sentence (also segment 0)
    segments: list[ScriptSegment]      # includes the hook as the first segment
    caption: str                       # Instagram caption incl. disclaimer
    hashtags: list[str]
    title: str = ""                    # internal working title

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments)


@dataclass
class Word:
    """One spoken word with timing from TTS alignment."""
    text: str
    start: float  # seconds
    end: float


@dataclass
class TTSResult:
    audio_path: str
    words: list[Word]
    duration: float  # seconds


# ── Stocks / daily story pipeline ──────────────────────────────────────────
@dataclass
class EarningsItem:
    """One company reporting quarterly figures on a given day."""
    ticker: str
    name: str
    market: str = "US"       # US | EU (drives the posting time zone)
    when: str = ""           # "vorbörslich" | "nachbörslich" | ""


@dataclass
class StockMetrics:
    """Chart + fundamentals snapshot for one ticker — NO sentiment, mirroring the
    trading-bot factor strategy (fundamentals AND chart only)."""
    ticker: str
    name: str
    sector: str
    market: str              # US | EU
    price: float
    currency: str
    sma20: float
    sma50: float
    rsi: float
    atr: float
    tech_score: float        # 0–1
    fund_score: float        # 0–1
    pe: float | None = None
    revenue_growth: float | None = None   # fraction, e.g. 0.18 = +18 %
    profit_margin: float | None = None     # fraction
    dividend_yield: float | None = None    # yfinance dividendYield (fraction or %, normalise on use)
    history_closes: list[float] = field(default_factory=list)  # recent closes for the chart

    @property
    def blended(self) -> float:
        # weights live in config so the mix stays tunable (default 0.5 / 0.5)
        import config
        return round(
            config.STOCK_W_TECH * self.tech_score + config.STOCK_W_FUND * self.fund_score, 4
        )


@dataclass
class Slide:
    """One carousel slide of a feed post."""
    heading: str
    body: str


@dataclass
class FeedPost:
    """A generated educational carousel feed post (5–8 slides)."""
    topic_slug: str
    title: str
    slides: list[Slide]
    caption: str
    hashtags: list[str]


@dataclass
class Candidate:
    """A metrics snapshot plus educational chart-derived risk marks and KI text.
    NOT a buy recommendation — framed as watchlist/education (BaFin finfluencer rules)."""
    metrics: StockMetrics
    entry: float             # reference level (last close)
    stop_loss: float         # chart/ATR-derived risk mark
    take_profit: float       # chart/ATR-derived potential mark
    # Educational texts per story card (simple, Instagram-friendly, slightly detailed):
    chart_text: str = ""         # what the chart shows
    fundamental_text: str = ""   # what the fundamentals show
    overall_text: str = ""       # the combined picture
    category: str = ""           # optional label, e.g. "TREND-AKTIE" (news-driven pick)
    trend_reason: str = ""       # one-line why this stock is trending (news)
