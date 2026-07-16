"""ElevenLabs TTS via the with-timestamps REST endpoint (no SDK dependency).
Returns character-level alignment which we fold into word timestamps."""
import base64
from pathlib import Path

import httpx

import config
from src.content import usage
from src.models import TTSResult, Word

_API_BASE = "https://api.elevenlabs.io/v1"


class TTSBudgetExceeded(RuntimeError):
    pass


def _chars_to_words(text_chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    """Fold ElevenLabs character alignment into per-word timings."""
    words: list[Word] = []
    current = ""
    w_start = 0.0
    for ch, start, end in zip(text_chars, starts, ends):
        if ch.isspace():
            if current:
                words.append(Word(text=current, start=w_start, end=end))
                current = ""
            continue
        if not current:
            w_start = start
        current += ch
    if current:
        words.append(Word(text=current, start=w_start, end=ends[-1] if ends else w_start))
    return words


class ElevenLabsTTS:
    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        if usage.tts_budget_exceeded(len(text)):
            raise TTSBudgetExceeded("TTS-Tagesbudget erschöpft")

        url = f"{_API_BASE}/text-to-speech/{config.ELEVENLABS_VOICE_ID}/with-timestamps"
        response = httpx.post(
            url,
            headers={"xi-api-key": config.ELEVENLABS_API_KEY},
            json={
                "text": text,
                "model_id": config.ELEVENLABS_MODEL,
                "output_format": "mp3_44100_128",
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()

        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        usage.record_tts(len(text), "voiceover")

        alignment = data.get("alignment") or {}
        words = _chars_to_words(
            alignment.get("characters", []),
            alignment.get("character_start_times_seconds", []),
            alignment.get("character_end_times_seconds", []),
        )
        duration = words[-1].end if words else 0.0
        return TTSResult(audio_path=str(out_path), words=words, duration=duration)
