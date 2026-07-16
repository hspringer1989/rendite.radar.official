"""ffmpeg composition: per-segment b-roll (or animated gradient fallback),
voiceover + optional ducked music, burned-in karaoke subtitles → 1080×1920 MP4."""
import random
import shutil
import subprocess
from pathlib import Path

from loguru import logger

import config
from src.models import ReelScript, TTSResult
from src.render.subtitles import build_ass

_TAIL_SECONDS = 0.4  # short hold on the last frame after the voiceover ends
_GRADIENT = "gradients=s={w}x{h}:c0=0x0B1E3A:c1=0x123B2E:speed=0.03"


def ffmpeg_available() -> bool:
    return shutil.which(config.FFMPEG_BIN) is not None


def _filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter string (Windows drive colon)."""
    return str(path).replace("\\", "/").replace(":", "\\:")


def segment_times(script: ReelScript, tts: TTSResult) -> list[tuple[float, float]]:
    """Map TTS word timings onto script segments by word count."""
    words = tts.words
    times: list[tuple[float, float]] = []
    cursor = 0
    for i, segment in enumerate(script.segments):
        count = len(segment.text.split())
        chunk = words[cursor:cursor + count]
        if chunk:
            start = times[-1][1] if times else 0.0
            end = chunk[-1].end
        else:  # tokenization drift: spread the remainder evenly
            start = times[-1][1] if times else 0.0
            remaining = len(script.segments) - i
            end = start + max(0.5, (tts.duration - start) / max(remaining, 1))
        times.append((start, max(end, start + 0.5)))
        cursor += count
    # last segment absorbs the tail hold
    start, end = times[-1]
    times[-1] = (start, max(end, tts.duration) + _TAIL_SECONDS)
    return times


def pick_music() -> Path | None:
    tracks = [
        p for p in Path(config.MUSIC_DIR).glob("*")
        if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac")
    ]
    return random.choice(tracks) if tracks else None


def render_reel(
    script: ReelScript,
    tts: TTSResult,
    broll_paths: list[str | None],
    out_path: Path,
    music_path: Path | None = None,
) -> Path:
    """Compose the final reel. `broll_paths` has one entry per segment (None → gradient)."""
    w, h = config.REEL_WIDTH, config.REEL_HEIGHT
    times = segment_times(script, tts)
    ass_path = build_ass(tts.words, out_path.with_suffix(".ass"))

    cmd: list[str] = [config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error"]
    filters: list[str] = []
    labels: list[str] = []

    for i, ((start, end), clip) in enumerate(zip(times, broll_paths)):
        duration = end - start
        idx = len(labels)  # inputs are appended in segment order
        if clip:
            cmd += ["-i", clip]
            filters.append(
                f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1,fps=30,"
                f"tpad=stop_mode=clone:stop_duration={duration:.3f},"
                f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[v{i}]"
            )
        else:
            cmd += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", _GRADIENT.format(w=w, h=h)]
            filters.append(f"[{idx}:v]fps=30,setsar=1,trim=duration={duration:.3f}[v{i}]")
        labels.append(f"[v{i}]")

    voice_idx = len(labels)
    cmd += ["-i", tts.audio_path]

    music_idx = None
    if music_path:
        music_idx = voice_idx + 1
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]

    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0[vcat]")
    filters.append(f"[vcat]ass=filename='{_filter_path(ass_path)}'[vout]")

    if music_idx is not None:
        filters.append(
            f"[{voice_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo[voice];"
            f"[{music_idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={config.MUSIC_VOLUME_DB}dB[music];"
            f"[voice][music]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = f"{voice_idx}:a"

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", audio_map,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]

    logger.info(f"Rendere Reel ({len(labels)} Segmente, {times[-1][1]:.1f}s) → {out_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fehlgeschlagen: {result.stderr[-2000:]}")
    return out_path
