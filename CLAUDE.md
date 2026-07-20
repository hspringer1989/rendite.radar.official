# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt

python main.py collect            # collect + score trends only
python main.py generate           # produce one reel end-to-end → review queue
python main.py stocks             # build today's earnings + watchlist story cards → review
python main.py verify-ig          # read-only check of the IG token/account/permissions
python main.py run                # scheduler loop: review bot + reel & story slots + insights
python main.py publish --reel 3   # manually publish a specific reel
python main.py post-story --story 7  # manually publish a specific story card
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

### Daily stock stories (`python main.py stocks`)  — `src/stocks/`

A second content path, independent of the reel pipeline: **Instagram story cards**
(1080×1920 JPGs, not videos) for the daily stock routine.

```
EarningsCalendar.todays(universe)   src/stocks/market_data.py  (yfinance | fake)
        │  companies reporting quarterly figures today
        ▼
select_candidates(universe, N)      src/stocks/analyzer.py
  blended = STOCK_W_TECH·technical + STOCK_W_FUND·fundamental   (NO sentiment,
  like the trading-bot factor strategy) → top-N, DISTINCT sectors
        │  chart-derived risk marks: ATR stop/take (indicators.risk_levels)
        ▼
one budget-gated Claude call        analyzer._attach_analysis  (purpose="stock_analysis")
  educational text per candidate + overall take; rule-based fallback if over budget
        ▼
story cards (Pillow)                src/stocks/story_cards.py
  earnings card + watchlist-overview card + one card per candidate
        ▼
StoryRow(pending_review)            src/storage/database.py  (table `stories`)
        ▼
Telegram photo review [✅ Posten | ❌]   send_photo_for_review / apply_story_decision
        ▼
publish_story (media_type=STORIES)  src/publish/instagram.py
  stage JPG under public URL → STORIES container → poll → media_publish → delete
```

- **Ports & fakes** like the rest: `STOCK_DATA_PROVIDER=fake` (`FakeMarketData` +
  `FakeEarningsCalendar`) runs the whole path offline; `indicators.py` is pure
  (SMA/RSI/ATR, technical/fundamental score, risk levels) and unit-tested with
  synthetic inputs. yfinance/Pillow are imported lazily inside methods.
- **Scheduler (`run`)** builds the cards once daily at `STOCK_STORY_SLOT` (→ Telegram
  review), then posts approved cards: earnings + watchlist-overview at
  `STORY_POST_EARNINGS_SLOT`, candidate cards spread over `STORY_SLOTS_EU` /
  `STORY_SLOTS_US` (local time; one story per slot, matched to the card's `market`).
  `publish_next_story(kinds, market)` picks the oldest approved match.
- Story cards bake ALL text into the image (Graph API stories have no
  stickers/links). No emoji in cards — the bundled fonts render them as tofu;
  emoji live only in Telegram captions. Story posting needs `PUBLIC_MEDIA_*`
  (public image URL) just like reels.

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
