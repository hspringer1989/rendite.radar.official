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
