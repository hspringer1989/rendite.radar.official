# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt

python main.py collect            # collect + score trends only
python main.py generate           # produce one reel end-to-end → review queue
python main.py run                # scheduler loop: Telegram review bot + posting slots + insights
python main.py publish --reel 3   # manually publish a specific reel
python main.py status             # queue counts, Claude budget, last posts

python -m pytest tests/           # offline: fake LLM/TTS, no network; ffmpeg test auto-skips
```

## Architecture

Autopilot that finds trending finance topics, produces German voiceover reels and
posts them to Instagram after human approval (Telegram review queue). Monetization
via a link-in-bio page with broker affiliate offers (Phase 4).

```
Collectors (google_trends | reddit | rss)      src/collectors/
        │  dedup via trends.uid
        ▼
Trend scorer — one batched Haiku call          src/content/scorer.py
  0.45·viral + 0.30·niche_fit + 0.25·monetization ≥ MIN_TREND_SCORE
        ▼
Script agent (Sonnet): hook-first German       src/content/script_agent.py
  script, caption, hashtags; compliance rules in the system prompt,
  "Keine Anlageberatung" disclaimer enforced in code
        ▼
TTS with word timestamps                       src/tts/  (elevenlabs | fake)
        ▼
Renderer (ffmpeg): per-segment Pexels b-roll   src/render/
  (or animated gradient fallback), karaoke ASS subtitles, music bed
  → 1080×1920 H.264
        ▼
Telegram review queue [✅ Posten|🔄 Neu|❌]      src/review/telegram_bot.py
        ▼
Publisher: Instagram Graph API                 src/publish/instagram.py
  stage MP4 under public URL → container → poll → publish → delete file
```

Reel status flow: `draft → pending_review → approved → published`
(reviewer can set `rejected` or `regenerate`; failures land in `failed` with `error`).

### Ports & fakes

Every paid/external dependency sits behind a port with an offline fake, so the whole
pipeline runs end-to-end without keys (`LLM_PROVIDER=fake`, `TTS_PROVIDER=fake`, no
Pexels key → gradient backgrounds, no Telegram → reels wait in DB):
`LLMProvider` (`src/content/llm.py`), `TTSProvider` (`src/tts/base.py`),
`PexelsBroll` (returns None → renderer falls back).

### Cost control (trading-bot pattern)

`src/content/usage.py`: hard daily gates — `CLAUDE_DAILY_BUDGET_EUR` (all Claude calls)
and `TTS_DAILY_BUDGET_CHARS` (ElevenLabs). No automatic call ever exceeds them.
Trend scoring uses `CLAUDE_MODEL_FAST` (Haiku, batched); only script generation uses
`CLAUDE_MODEL` (Sonnet).

### Database

SQLite at `data/reel_autopilot.db` (SQLAlchemy, `src/storage/database.py`):
`trends` (dedup + scores), `reels` (script/paths/status), `metrics` (daily insights),
`api_usage` (budget gating).

### Scheduler (`python main.py run`)

Minute tick: process 🔄 regenerations → keep review queue filled (generates when
queue < number of `POSTING_SLOTS`, 1h cooldown) → publish oldest approved reel at
each slot (local `TIMEZONE`) → fetch insights daily at 07:00. Rendering/LLM work
runs via `asyncio.to_thread` so the Telegram poller stays responsive.

## Compliance (do not weaken)

- Scripts must stay educational/news-driven — no buy/sell recommendations for
  specific securities (BaFin finfluencer rules). The disclaimer append in
  `script_agent.py` is a safety net, not decoration.
- Affiliate content must be labelled as Werbung (caption + landing page).
- Only royalty-free music from `assets/music/` — API-published reels have no license
  for Instagram's in-app music library.

## Setup

Manual steps (Instagram/Meta app, ElevenLabs, Telegram, affiliate networks):
see `docs/SETUP.md`. Local dev `.env` uses fakes; production values per `.env.example`.
