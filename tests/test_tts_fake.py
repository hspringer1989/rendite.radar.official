import wave

from src.tts.fake import FakeTTS


def test_fake_tts_writes_wav_with_word_timings(tmp_path):
    result = FakeTTS().synthesize("Drei Fehler kosten dich Geld", tmp_path / "voice.mp3")

    assert result.audio_path.endswith(".wav")
    with wave.open(result.audio_path, "rb") as wav:
        assert wav.getnframes() > 0

    assert len(result.words) == 5
    assert result.words[0].start == 0.0
    assert result.words[-1].end == result.duration
    # monotonically increasing, non-overlapping
    for a, b in zip(result.words, result.words[1:]):
        assert a.end <= b.start + 1e-9
