"""Candidate selection + educational analysis texts (FakeMarketData + FakeLLM)."""
import json

from src.content.llm import FakeLLM
from src.stocks.analyzer import build_candidates, select_candidates
from src.stocks.market_data import FakeMarketData

_UNIVERSE = ["AAPL", "JPM", "XOM", "SAP.DE", "ALV.DE"]


def _fake_llm() -> FakeLLM:
    payload = json.dumps({
        "candidates": [
            {"ticker": t,
             "chart": f"Der Chart von {t} zeigt einen ruhigen Aufwärtstrend.",
             "fundamental": f"Fundamental wirkt {t} solide bewertet.",
             "overall": f"Gesamtbild {t}: Chart und Fundamental passen zusammen."}
            for t in _UNIVERSE
        ],
    })
    return FakeLLM({"stock_analysis": payload})


def test_select_candidates_diversifies_sectors():
    picked = select_candidates(FakeMarketData(), _UNIVERSE, count=3)
    assert len(picked) == 3
    assert len({m.sector for m in picked}) == 3  # distinct sectors


def test_select_candidates_respects_exclude():
    md = FakeMarketData()
    first = select_candidates(md, _UNIVERSE, count=3)
    excluded = {first[0].ticker}
    second = select_candidates(md, _UNIVERSE, count=3, exclude=excluded)
    assert first[0].ticker not in [m.ticker for m in second]


def test_select_candidates_last_resort_when_all_excluded():
    md = FakeMarketData()
    picked = select_candidates(md, _UNIVERSE, count=3, exclude=set(_UNIVERSE))
    assert len(picked) == 3  # reuses cooldown tickers rather than returning nothing


def test_build_candidates_has_levels_and_three_texts():
    cands = build_candidates(FakeMarketData(), _UNIVERSE, _fake_llm(), count=3)
    assert len(cands) == 3
    for c in cands:
        assert c.stop_loss < c.entry < c.take_profit
        assert c.chart_text and c.fundamental_text and c.overall_text
        assert c.metrics.history_closes  # closes stored for the chart


def test_analysis_sanitises_buy_imperative():
    llm = FakeLLM({"stock_analysis": json.dumps({
        "candidates": [{"ticker": "AAPL",
                        "chart": "AAPL jetzt kaufen, klares Signal.",
                        "fundamental": "solide", "overall": "stimmig"}],
    })})
    cands = build_candidates(FakeMarketData(), ["AAPL"], llm, count=1)
    assert "kaufen" not in cands[0].chart_text.lower()


def test_fallback_texts_when_ticker_missing_in_response():
    llm = FakeLLM({"stock_analysis": json.dumps({"candidates": []})})
    cands = build_candidates(FakeMarketData(), ["AAPL"], llm, count=1)
    # rule-based fallback kicked in for all three texts
    assert "50-Tage-Linie" in cands[0].chart_text
    assert "KGV" in cands[0].fundamental_text
    assert cands[0].overall_text
