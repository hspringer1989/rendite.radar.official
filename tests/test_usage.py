import config
from src.content import usage


def test_claude_budget_gate(monkeypatch):
    monkeypatch.setattr(config, "CLAUDE_DAILY_BUDGET_EUR", 0.01)
    assert not usage.claude_budget_exceeded()
    # a big Sonnet call: 1M input tokens ≈ 2.80 € > cap
    usage.record_claude("claude-sonnet-4-6", 1_000_000, 0, "test")
    assert usage.claude_budget_exceeded()


def test_tts_budget_gate(monkeypatch):
    monkeypatch.setattr(config, "TTS_DAILY_BUDGET_CHARS", 1000)
    assert not usage.tts_budget_exceeded(900)
    usage.record_tts(900, "test")
    assert usage.tts_budget_exceeded(200)
    assert not usage.tts_budget_exceeded(100)


def test_unknown_model_priced_as_mid_tier():
    usage.record_claude("claude-fable-5", 1000, 1000, "test")  # must not raise
