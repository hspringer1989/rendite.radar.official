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


def init_db(db_path: str | None = None) -> None:
    global _engine, _session_factory
    path = db_path or str(config.DB_PATH)
    _engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(_engine)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


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
