"""Real ffmpeg smoke test — skipped when ffmpeg is not installed locally."""
import pytest

from src.models import ReelScript, ScriptSegment
from src.render.renderer import ffmpeg_available, render_reel, segment_times
from src.tts.fake import FakeTTS

_SCRIPT = ReelScript(
    hook="Diese drei Fehler kosten dich Geld.",
    segments=[
        ScriptSegment(text="Diese drei Fehler kosten dich Geld.", broll_query="money"),
        ScriptSegment(text="Fehler eins ist das Girokonto.", broll_query="bank"),
    ],
    caption="Test", hashtags=["#test"],
)


def _tts(tmp_path):
    return FakeTTS().synthesize(_SCRIPT.full_text, tmp_path / "voice.mp3")


def test_segment_times_cover_full_duration(tmp_path):
    tts = _tts(tmp_path)
    times = segment_times(_SCRIPT, tts)
    assert len(times) == 2
    assert times[0][0] == 0.0
    assert times[0][1] == pytest.approx(times[1][0])
    assert times[-1][1] >= tts.duration


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg nicht installiert")
def test_render_gradient_reel(tmp_path):
    tts = _tts(tmp_path)
    out = render_reel(_SCRIPT, tts, [None, None], tmp_path / "reel.mp4")
    assert out.exists()
    assert out.stat().st_size > 10_000
