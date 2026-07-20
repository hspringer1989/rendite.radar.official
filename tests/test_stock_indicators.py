"""Pure indicator/scoring functions — synthetic inputs, no network."""
from src.stocks import indicators as ind


def test_sma_and_none_when_too_few():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 5) is None


def test_rsi_all_gains_is_100():
    assert ind.rsi(list(range(1, 40))) == 100.0


def test_rsi_none_when_too_few():
    assert ind.rsi([1, 2, 3]) is None


def test_atr_positive_for_ranging_series():
    highs = [10 + i for i in range(20)]
    lows = [9 + i for i in range(20)]
    closes = [9.5 + i for i in range(20)]
    assert ind.atr(highs, lows, closes) > 0


def test_technical_score_uptrend_high():
    # price above rising averages, healthy RSI, positive momentum → strong
    score = ind.technical_score(110, sma20=105, sma50=100, rsi_value=55, mom=0.08)
    assert score > 0.75


def test_technical_score_downtrend_low():
    score = ind.technical_score(90, sma20=95, sma50=100, rsi_value=30, mom=-0.1)
    assert score < 0.4


def test_technical_score_neutral_on_missing_data():
    # all ingredients missing → averages to the neutral 0.5 fallbacks
    assert ind.technical_score(0, None, None, None, 0.0) == 0.5


def test_fundamental_score_prefers_cheap_growing():
    strong = ind.fundamental_score(pe=12, revenue_growth=0.2, profit_margin=0.25)
    weak = ind.fundamental_score(pe=60, revenue_growth=-0.1, profit_margin=-0.05)
    assert strong > 0.8
    assert weak < 0.3


def test_risk_levels_atr_based():
    stop, take = ind.risk_levels(100.0, atr_value=2.0, stop_mult=2.0, tp_mult=4.0)
    assert stop == 96.0
    assert take == 108.0


def test_risk_levels_percentage_fallback_without_atr():
    stop, take = ind.risk_levels(100.0, atr_value=None, stop_mult=2.0, tp_mult=4.0)
    assert stop == 94.0   # 6 % fallback
    assert take == 112.0  # 12 % fallback
