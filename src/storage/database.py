"""SQLite persistence (SQLAlchemy ORM), pattern borrowed from trading-bot."""
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import config

# Reel lifecycle: draft → pending_review → approved → published
#                              └→ rejected / regenerate       └→ failed
REEL_STATUSES = (
    "draft", "pending_review", "approved", "rejected", "regenerate", "published", "failed",
)


class Base(DeclarativeBase):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrendRow(Base):
    __tablename__ = "trends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    popularity: Mapped[float] = mapped_column(Float, default=0.0)
    # new → scored → used | skipped
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    score_total: Mapped[float] = mapped_column(Float, default=0.0)
    score_viral: Mapped[float] = mapped_column(Float, default=0.0)
    score_fit: Mapped[float] = mapped_column(Float, default=0.0)
    score_monetization: Mapped[float] = mapped_column(Float, default=0.0)
    score_reasoning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow)


class ReelRow(Base):
    __tablename__ = "reels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trend_id: Mapped[int] = mapped_column(Integer, index=True)
    script_json: Mapped[str] = mapped_column(Text, default="")
    audio_path: Mapped[str] = mapped_column(Text, default="")
    video_path: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    ig_media_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow)
    published_at: Mapped[str] = mapped_column(String(40), default="")


class StoryRow(Base):
    """A rendered Instagram-story card in the review/posting queue.
    kind: earnings | candidates | candidate. Same status flow as reels."""
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    part: Mapped[str] = mapped_column(String(12), default="", index=True)  # candidate: chart|fundamental|overall
    ticker: Mapped[str] = mapped_column(String(16), default="")  # only for kind='candidate'
    market: Mapped[str] = mapped_column(String(4), default="")   # US | EU
    image_path: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    analysis_json: Mapped[str] = mapped_column(Text, default="")
    trade_date: Mapped[str] = mapped_column(String(10), index=True, default="")  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    ig_media_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow)
    published_at: Mapped[str] = mapped_column(String(40), default="")


class FeedTopicRow(Base):
    """Backlog of educational feed-post topics (seeded once). status: queued | used."""
    __tablename__ = "feed_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text, default="")   # guidance for the generator
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)


class FeedPostRow(Base):
    """A generated multi-slide carousel feed post. Same review flow as stories."""
    __tablename__ = "feed_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_slug: Mapped[str] = mapped_column(String(64), index=True, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    slides_json: Mapped[str] = mapped_column(Text, default="")        # [{heading, body}, …]
    image_paths_json: Mapped[str] = mapped_column(Text, default="")   # [path, …] in order
    caption: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    ig_media_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow)
    published_at: Mapped[str] = mapped_column(String(40), default="")


# Seed backlog: the first two are the user's requested launch posts, then evergreen ideas.
_FEED_TOPIC_SEED = [
    ("strategie-auswahl", "Wie wir Aktien für unsere Analysen auswählen",
     "Erkläre die Auswahl-Strategie fundiert und einfach: Kombination aus CHARTTECHNIK "
     "(Trendstruktur über SMA20/50, RSI-Bänder 45-65 gesund) und FUNDAMENTALDATEN (KGV, "
     "Umsatzwachstum, Gewinnmarge). Blended-Score 50% Chart + 50% Fundamental, Auswahl der "
     "Top-Titel über VERSCHIEDENE Branchen (Diversifikation). Risiko-/Zielmarken aus dem ATR "
     "(2x/4x). Ampel grün/gelb/rot = bullisch/neutral/bärisch, rein beobachtend. "
     "Betone: datenbasiert, transparent, KEINE Anlageberatung."),
    ("trading-bot-claude-code",
     "Trading-Bot mit Claude Code bauen & ans Echtgeld-Depot anschließen",
     "Kompakte Schritt-für-Schritt-Anleitung anhand eines echten Projekts: 1) Strategie "
     "definieren, 2) Marktdaten (z.B. yfinance), 3) Signal-Analyse mit Claude, 4) "
     "Risk-Management (Position-Sizing, Stop-Loss, ATR-Bracket-Orders), 5) Broker per API "
     "anbinden (Interactive Brokers), 6) ERST Paper-Trading, dann Echtgeld. Deutliche "
     "RISIKO-WARNUNG: echtes Geld, Totalverlust möglich, keine Gewinngarantie, KEINE "
     "Anlageberatung. Ton: motivierend aber ehrlich."),
    ("etf-basics", "ETFs einfach erklärt: der bequeme Einstieg",
     "Was ist ein ETF, wie funktioniert Streuung, TER/Kosten, thesaurierend vs. ausschüttend, "
     "Sparplan-Idee. Einfach, edukativ, keine Empfehlung."),
    ("kgv-erklaert", "Das KGV: wie teuer ist eine Aktie wirklich?",
     "KGV = Kurs-Gewinn-Verhältnis einfach erklärt, was hoch/niedrig bedeutet, Grenzen der "
     "Kennzahl, Branchenunterschiede. Edukativ."),
    ("rsi-erklaert", "RSI: das Fieberthermometer für Aktien",
     "RSI erklärt: Schwungkraft-Maß, überkauft >70 / überverkauft <30, gesunder Bereich, "
     "warum kein Signal allein reicht. Edukativ."),
    ("stop-loss", "Stop-Loss: wie man Verluste begrenzt",
     "Stop-Loss-Prinzip, ATR-basierte Marken, warum Risikomanagement wichtiger ist als das "
     "perfekte Einstiegssignal. Edukativ."),
    ("diversifikation", "Warum Streuung dein bester Freund ist",
     "Diversifikation über Branchen/Regionen, Klumpenrisiko, Beispiel. Edukativ."),
    ("zinseszins", "Zinseszins: der stille Vermögens-Booster",
     "Zinseszins-Effekt, Zeit als Hebel, einfaches Rechenbeispiel. Edukativ."),
    ("anlegerfehler", "5 Fehler, die Anfänger an der Börse machen",
     "Häufige Fehler: Panikverkäufe, Market-Timing, Klumpenrisiko, Gebühren ignorieren, kein "
     "Plan. Edukativ, mit Augenzwinkern."),
    ("earnings-season", "Earnings-Season: worauf es bei Quartalszahlen ankommt",
     "Was Quartalszahlen sind, EPS/Umsatz/Guidance, warum Kurse trotz guter Zahlen fallen "
     "können. Edukativ."),
]


class MetricRow(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reel_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    plays: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)


class ApiUsageRow(Base):
    __tablename__ = "api_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    provider: Mapped[str] = mapped_column(String(20), index=True)  # claude | elevenlabs
    purpose: Mapped[str] = mapped_column(String(40), default="")
    cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    units: Mapped[int] = mapped_column(Integer, default=0)  # tokens or characters
    created_at: Mapped[str] = mapped_column(String(40), default=_utcnow)


_engine = None
_session_factory = None


def _migrate(engine) -> None:
    """Lightweight additive migrations for SQLite (create_all never ALTERs)."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(stories)").fetchall()}
        if cols and "part" not in cols:
            conn.exec_driver_sql("ALTER TABLE stories ADD COLUMN part VARCHAR(12) DEFAULT ''")


def _seed_feed_topics(session_factory) -> None:
    """Insert the seed feed-post topics once (idempotent by slug)."""
    session = session_factory()
    try:
        existing = {s for (s,) in session.execute(select(FeedTopicRow.slug)).all()}
        for pos, (slug, title, brief) in enumerate(_FEED_TOPIC_SEED):
            if slug not in existing:
                session.add(FeedTopicRow(slug=slug, title=title, brief=brief, position=pos))
        session.commit()
    finally:
        session.close()


def init_db(db_path: str | None = None) -> None:
    global _engine, _session_factory
    path = db_path or str(config.DB_PATH)
    _engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(_engine)
    _migrate(_engine)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    _seed_feed_topics(_session_factory)


@contextmanager
def session_scope():
    if _session_factory is None:
        init_db()
    session: Session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def trend_uid_known(session: Session, uid: str) -> bool:
    return session.execute(select(TrendRow.id).where(TrendRow.uid == uid)).first() is not None


def daily_usage_eur(session: Session, provider: str, date: str) -> float:
    total = session.execute(
        select(func.sum(ApiUsageRow.cost_eur))
        .where(ApiUsageRow.provider == provider, ApiUsageRow.date == date)
    ).scalar()
    return float(total or 0.0)


def daily_usage_units(session: Session, provider: str, date: str) -> int:
    total = session.execute(
        select(func.sum(ApiUsageRow.units))
        .where(ApiUsageRow.provider == provider, ApiUsageRow.date == date)
    ).scalar()
    return int(total or 0)
