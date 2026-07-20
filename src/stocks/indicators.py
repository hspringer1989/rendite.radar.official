"""Pure technical/fundamental scoring functions — no I/O, no yfinance, no config
side effects — so they unit-test with synthetic inputs (same discipline as the
trading-bot's pure decision functions). All inputs are plain float lists.

Scoring philosophy (factor strategy, no sentiment):
- technical_score: trend alignment (price > SMA20 > SMA50) + healthy RSI band +
  positive momentum, each contributing to a 0–1 score.
- fundamental_score: valuation (P/E) + revenue growth + profit margin, 0–1.
"""
from __future__ import annotations


def sma(values: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` values, or None if too few."""
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder-style RSI over `period` closes. Returns 0–100 or None if too few."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for prev, cur in zip(closes[-period - 1:-1], closes[-period:]):
        change = cur - prev
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Average True Range over `period` bars, or None if too few bars."""
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs: list[float] = []
    for i in range(n - period, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / period


def momentum(closes: list[float], lookback: int = 10) -> float:
    """Relative price change over `lookback` bars (fraction). 0.0 if too few."""
    if len(closes) <= lookback or closes[-lookback - 1] == 0:
        return 0.0
    return (closes[-1] - closes[-lookback - 1]) / closes[-lookback - 1]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def technical_score(
    price: float,
    sma20: float | None,
    sma50: float | None,
    rsi_value: float | None,
    mom: float,
) -> float:
    """0–1 chart score. Neutral 0.5 when the ingredient is missing (data error),
    matching the trading-bot's neutral fallback convention."""
    parts: list[float] = []

    # Trend alignment: reward price above the averages and a rising stack.
    if sma20 is not None and sma50 is not None and price > 0:
        trend = 0.0
        trend += 0.5 if price > sma20 else 0.0
        trend += 0.3 if sma20 > sma50 else 0.0
        trend += 0.2 if price > sma50 else 0.0
        parts.append(trend)
    else:
        parts.append(0.5)

    # RSI: best in the 45–65 healthy-uptrend band; penalise overbought/oversold.
    if rsi_value is not None:
        if 45 <= rsi_value <= 65:
            parts.append(1.0)
        elif rsi_value < 45:
            parts.append(_clamp01(rsi_value / 45.0))          # rises toward 1 at 45
        else:  # > 65, cooling toward overbought
            parts.append(_clamp01((100 - rsi_value) / 35.0))
    else:
        parts.append(0.5)

    # Momentum: +10 % over the lookback maps to ~1.0, negative → toward 0.
    parts.append(_clamp01(0.5 + mom * 5.0))

    return round(sum(parts) / len(parts), 4)


def fundamental_score(
    pe: float | None,
    revenue_growth: float | None,
    profit_margin: float | None,
) -> float:
    """0–1 fundamentals score. Neutral 0.5 per missing ingredient."""
    parts: list[float] = []

    # Valuation: reward reasonable P/E, penalise very high / negative earnings.
    if pe is not None:
        if pe <= 0:
            parts.append(0.2)                                 # no/negative earnings
        elif pe < 15:
            parts.append(1.0)
        elif pe < 30:
            parts.append(_clamp01((30 - pe) / 15.0))
        else:
            parts.append(0.1)
    else:
        parts.append(0.5)

    # Revenue growth: +20 % → ~1.0, flat → 0.5, shrinking → toward 0.
    if revenue_growth is not None:
        parts.append(_clamp01(0.5 + revenue_growth * 2.5))
    else:
        parts.append(0.5)

    # Profit margin: 20 %+ → strong, negative → weak.
    if profit_margin is not None:
        parts.append(_clamp01(0.3 + profit_margin * 3.5))
    else:
        parts.append(0.5)

    return round(sum(parts) / len(parts), 4)


def sma_series(values: list[float], window: int) -> list[float | None]:
    """Rolling SMA aligned to `values` (None until enough data) — for chart drawing."""
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - window:i + 1]) / window)
    return out


# Traffic-light tendency: an OBSERVATIONAL read of the data, not a buy/sell call.
# pos ≥ 0.60 (green), neu 0.40–0.60 (yellow), neg < 0.40 (red).
_TENDENCY_LABELS = {
    "chart": {"pos": "Bullisch", "neu": "Neutral", "neg": "Bärisch"},
    "fund": {"pos": "Stark", "neu": "Neutral", "neg": "Schwach"},
    "overall": {"pos": "Eher positiv", "neu": "Gemischt", "neg": "Eher schwach"},
}


def tendency(score: float, kind: str = "chart") -> tuple[str, str]:
    """Map a 0–1 score to (level, label) for the traffic-light badge.
    level ∈ {'pos','neu','neg'}; label depends on the dimension (chart/fund/overall)."""
    if score >= 0.60:
        level = "pos"
    elif score >= 0.40:
        level = "neu"
    else:
        level = "neg"
    return level, _TENDENCY_LABELS.get(kind, _TENDENCY_LABELS["chart"])[level]


def risk_levels(
    entry: float,
    atr_value: float | None,
    stop_mult: float,
    tp_mult: float,
    pct_fallback_stop: float = 0.06,
    pct_fallback_tp: float = 0.12,
) -> tuple[float, float]:
    """Chart-derived stop-loss / take-profit marks. ATR-based when available,
    else a percentage fallback (mirrors the trading-bot's ATR-or-% convention)."""
    if atr_value and atr_value > 0:
        stop = entry - stop_mult * atr_value
        take = entry + tp_mult * atr_value
    else:
        stop = entry * (1 - pct_fallback_stop)
        take = entry * (1 + pct_fallback_tp)
    return round(max(stop, 0.0), 2), round(take, 2)
