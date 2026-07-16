"""Offline TTS stand-in: writes silent WAV audio with evenly spaced word
timestamps so the full render pipeline can run without an API key."""
import wave
from pathlib import Path

from src.models import TTSResult, Word

_SECONDS_PER_WORD = 0.42  # ≈ German speech pace
_SAMPLE_RATE = 44100


class FakeTTS:
    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        tokens = text.split()
        duration = max(1.0, len(tokens) * _SECONDS_PER_WORD)

        out_path = out_path.with_suffix(".wav")
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_SAMPLE_RATE)
            wav.writeframes(b"\x00\x00" * int(duration * _SAMPLE_RATE))

        words = [
            Word(text=tok, start=i * _SECONDS_PER_WORD, end=(i + 1) * _SECONDS_PER_WORD)
            for i, tok in enumerate(tokens)
        ]
        return TTSResult(audio_path=str(out_path), words=words, duration=duration)
