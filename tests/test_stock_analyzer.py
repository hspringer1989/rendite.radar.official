"""Candidate selection + educational analysis text (FakeMarketData + FakeLLM)."""
import json

from src.content.llm import FakeLLM
from src.stocks.analyzer import build_candidates, select_candidates
from src.stocks.market_data import FakeMarketData

_UNIVERSE = ["AAPL", "JPM", "XOM", "SAP.DE", "ALV.DE"]


def _fake_llm() -> FakeLLM:
    payload = json.dumps({
        "candidates": [
            {"ticker": t, "analysis": f"Edukative Einordnung zu {t}."}
            for t in _UNIVERSE
        ],
        "overall": "Sachliche Gesamteinordnung der Auswahl.",
    })
    return FakeLLM({"stock_analysis": payload})


def test_select_candidates_diversifies_sectors():
    picked = select_candidates(FakeMarketData(), _UNIVERSE, count=3)
    assert len(picked) == 3
    sectors = [m.sector for m in picked]
    assert len(set(sectors)) == 3  # distinct sectors


def test_build_candidates_has_levels_and_text():
    cands = build_candidates(FakeMarketData(), _UNIVERSE, _fake_llm(), count=3)
    assert len(cands) == 3
    for c in cands:
        assert c.stop_loss < c.entry < c.take_profit
        assert c.analysis  # some educational text present


def test_analysis_sanitises_buy_imperative():
    llm = FakeLLM({"stock_analysis": json.dumps({
        "candidates": [{"ticker": "AAPL", "analysis": "AAPL jetzt kaufen, klares Signal."}],
        "overall": "",
    })})
    cands = build_candidates(FakeMarketData(), ["AAPL"], llm, count=1)
    assert "kaufen" not in cands[0].analysis.lower()


def test_fallback_text_when_ticker_missing_in_response():
    llm = FakeLLM({"stock_analysis": json.dumps({"candidates": [], "overall": ""})})
    cands = build_candidates(FakeMarketData(), ["AAPL"], llm, count=1)
    assert "Charttechnik" in cands[0].analysis  # rule-based fallback kicked in
