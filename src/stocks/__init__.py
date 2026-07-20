"""Daily stock-story pipeline: today's earnings + chart/fundamental watchlist
candidates rendered as Instagram story cards, sent to the Telegram review queue.

Educational/watchlist framing only — no buy/sell recommendations (see CLAUDE.md
'Compliance'). Chart-derived stop-loss / take-profit are labelled as risk marks.
Analysis uses fundamentals AND chart only (no sentiment), like the trading-bot
factor strategy."""
