"""Builds an ASS subtitle file from TTS word timestamps: short 2–3-word chunks
with per-word karaoke highlighting, burned in by the renderer."""
from pathlib import Path

import config
from src.models import Word

_MAX_WORDS_PER_CHUNK = 3
_PUNCT_BREAK = (".", "!", "?", ":", ",", "—", "…")

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reel,Arial,96,&H0000E5FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,6,2,2,60,60,640,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")")


def chunk_words(words: list[Word]) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        current.append(word)
        if len(current) >= _MAX_WORDS_PER_CHUNK or word.text.endswith(_PUNCT_BREAK):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def build_ass(words: list[Word], out_path: Path) -> Path:
    """One dialogue event per chunk; \\k karaoke tags fill each word (white → accent)
    while it is spoken."""
    lines = [_ASS_HEADER.format(width=config.REEL_WIDTH, height=config.REEL_HEIGHT)]
    for chunk in chunk_words(words):
        start, end = chunk[0].start, chunk[-1].end
        parts = []
        for word in chunk:
            centis = max(1, round((word.end - word.start) * 100))
            parts.append(f"{{\\k{centis}}}{_escape(word.text)}")
        lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Reel,,0,0,0,,{' '.join(parts)}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8-sig")
    return out_path
