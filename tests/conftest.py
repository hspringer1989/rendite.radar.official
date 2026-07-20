import pytest

import config
from src.storage import database


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Fresh SQLite DB and output dirs per test; never touches real data/."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "reels")
    monkeypatch.setattr(config, "STORY_DIR", tmp_path / "stories")
    monkeypatch.setattr(config, "BROLL_CACHE_DIR", tmp_path / "broll")
    config.OUTPUT_DIR.mkdir()
    config.STORY_DIR.mkdir()
    config.BROLL_CACHE_DIR.mkdir()
    database.init_db(str(tmp_path / "test.db"))
    yield
