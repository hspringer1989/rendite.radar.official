"""TTS provider port: audio file + word-level timestamps (needed for
karaoke-style burned-in subtitles)."""
from abc import ABC, abstractmethod
from pathlib import Path

from src.models import TTSResult


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        """Render `text` as speech into `out_path`, returning word timestamps."""


def get_tts() -> TTSProvider:
    import config

    if config.TTS_PROVIDER == "elevenlabs":
        from src.tts.elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS()
    from src.tts.fake import FakeTTS

    return FakeTTS()
