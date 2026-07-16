import json

from src.content.llm import FakeLLM
from src.content.script_agent import generate_script
from src.models import TrendItem

_TREND = TrendItem(source="rss", title="EZB senkt Leitzins")


def _make(payload) -> FakeLLM:
    return FakeLLM({"generate_script": json.dumps(payload)})


_VALID = {
    "title": "Zinssenkung",
    "segments": [
        {"text": "Die EZB hat gerade dein Erspartes teurer gemacht.", "broll": "european central bank"},
        {"text": "Der Leitzins sinkt — das bedeutet weniger Zinsen auf dem Tagesgeld.", "broll": "piggy bank coins"},
    ],
    "caption": "Was die Zinssenkung für dich heißt.\n\n⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung.",
    "hashtags": ["#finanzen", "geld", "zwei wörter", ""],
}


def test_valid_script_parsed():
    script = generate_script(_TREND, _make(_VALID))
    assert script.hook.startswith("Die EZB")
    assert len(script.segments) == 2
    assert script.segments[1].broll_query == "piggy bank coins"
    assert script.full_text.count("EZB") == 1


def test_hashtags_normalized_and_filtered():
    script = generate_script(_TREND, _make(_VALID))
    # "geld" gets a #, multi-word and empty entries are dropped
    assert script.hashtags == ["#finanzen", "#geld"]


def test_missing_disclaimer_is_appended():
    payload = dict(_VALID, caption="Nur eine Caption ohne Hinweis.")
    script = generate_script(_TREND, _make(payload))
    assert "Anlageberatung" in script.caption


def test_too_few_segments_rejected():
    payload = dict(_VALID, segments=[{"text": "Nur ein Satz.", "broll": "x"}])
    assert generate_script(_TREND, _make(payload)) is None


def test_non_json_response_rejected():
    llm = FakeLLM({"generate_script": "Hier ist dein Skript: ..."})
    assert generate_script(_TREND, llm) is None
