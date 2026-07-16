"""End-to-end pipeline test with fakes only: no network, no ffmpeg."""
from pathlib import Path

import pytest
from sqlalchemy import select

import src.pipeline as pipeline
from src.collectors.base import Collector
from src.content.llm import builtin_fake
from src.models import TrendItem
from src.storage.database import ReelRow, TrendRow, session_scope


class StubCollector(Collector):
    name = "stub"

    def collect(self):
        return [
            TrendItem(source="stub", title="EZB senkt Leitzins überraschend"),
            TrendItem(source="stub", title="Neue Depot-Gebühren bei Neobrokern"),
        ]


class BrokenCollector(Collector):
    name = "broken"

    def collect(self):
        raise ConnectionError("Quelle nicht erreichbar")


def _fake_render(script, tts, broll_paths, out_path, music_path=None):
    Path(out_path).write_bytes(b"fake mp4")
    return Path(out_path)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(pipeline, "active_collectors", lambda: [StubCollector(), BrokenCollector()])
    monkeypatch.setattr(pipeline, "get_llm", builtin_fake)
    monkeypatch.setattr(pipeline, "render_reel", _fake_render)
    monkeypatch.setattr(pipeline.PexelsBroll, "fetch", lambda self, q, m: None)


def test_collect_and_score_dedups_and_survives_broken_source():
    assert pipeline.collect_and_score(builtin_fake()) == 2
    # second run: everything already known
    assert pipeline.collect_and_score(builtin_fake()) == 0
    with session_scope() as session:
        rows = session.execute(select(TrendRow)).scalars().all()
    assert len(rows) == 2
    assert all(r.status == "scored" and r.score_total > 0 for r in rows)


async def test_generate_once_end_to_end():
    reel_id = await pipeline.generate_once()
    assert reel_id is not None

    with session_scope() as session:
        reel = session.get(ReelRow, reel_id)
        trend = session.get(TrendRow, reel.trend_id)

    assert reel.status == "pending_review"
    assert Path(reel.video_path).exists()
    assert "Anlageberatung" in reel.caption
    assert "#finanzen" in reel.caption
    assert trend.status == "used"
    # the highest-scored trend was picked (builtin_fake scores index 0 highest)
    assert trend.title == "EZB senkt Leitzins überraschend"


async def test_regenerate_produces_new_reel_for_same_trend():
    reel_id = await pipeline.generate_once()
    with session_scope() as session:
        session.get(ReelRow, reel_id).status = "regenerate"

    new_ids = pipeline.handle_regenerates()
    assert len(new_ids) == 1
    with session_scope() as session:
        old = session.get(ReelRow, reel_id)
        new = session.get(ReelRow, new_ids[0])
    assert old.status == "rejected"
    assert new.status == "pending_review"
    assert new.trend_id == old.trend_id


async def test_no_trend_above_threshold(monkeypatch):
    import config

    monkeypatch.setattr(config, "MIN_TREND_SCORE", 0.99)
    assert await pipeline.generate_once() is None
