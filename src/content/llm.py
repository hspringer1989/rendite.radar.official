"""LLM provider port. Claude for production, FakeLLM for offline tests
(same idea as the LLMProvider port in Lead_Generator)."""
import json
import re
from abc import ABC, abstractmethod

from loguru import logger

import config
from src.content import usage


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, model: str, max_tokens: int, purpose: str) -> str:
        """Return the raw text completion. Raises BudgetExceeded if the daily cap is hit."""


class BudgetExceeded(RuntimeError):
    pass


class ClaudeProvider(LLMProvider):
    def __init__(self):
        import anthropic

        # timeout/max_retries: a hung call must never block a pipeline run
        self._client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY, timeout=120.0, max_retries=2
        )

    def complete(self, system: str, user: str, model: str, max_tokens: int, purpose: str) -> str:
        if usage.claude_budget_exceeded():
            raise BudgetExceeded("Claude-Tagesbudget erschöpft")
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        usage.record_claude(
            model, message.usage.input_tokens, message.usage.output_tokens, purpose
        )
        return message.content[0].text


class FakeLLM(LLMProvider):
    """Deterministic canned responses for tests: maps a purpose to a response."""

    def __init__(self, responses: dict[str, str]):
        self.responses = responses
        self.calls: list[dict] = []

    def complete(self, system: str, user: str, model: str, max_tokens: int, purpose: str) -> str:
        self.calls.append({"system": system, "user": user, "model": model, "purpose": purpose})
        return self.responses[purpose]


def parse_json_response(raw: str):
    """Parse a JSON object/array from an LLM response, tolerating ``` fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # strict=False tolerates literal control chars (e.g. newlines) inside strings.
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError as exc:
        logger.warning(f"LLM-Antwort kein gültiges JSON: {exc} — {cleaned[:120]}")
        return None


def builtin_fake() -> "FakeLLM":
    """Offline stand-in (LLM_PROVIDER=fake): lets the whole pipeline run end-to-end
    without API keys or costs — used for local dry-runs and tests."""
    scores = json.dumps([
        {"i": i, "viral": 0.8 - i * 0.05, "fit": 0.9, "monetization": 0.7,
         "reasoning": "Fake-Bewertung für Offline-Test"}
        for i in range(25)
    ])
    script = json.dumps({
        "title": "Offline-Testskript",
        "segments": [
            {"text": "Diese drei Geldfehler kosten dich zehntausende Euro.", "broll": "burning money close up"},
            {"text": "Fehler eins: Dein Geld liegt unverzinst auf dem Girokonto und verliert jedes Jahr an Wert.", "broll": "empty wallet person"},
            {"text": "Fehler zwei: Du wartest auf den perfekten Einstieg, statt einfach anzufangen.", "broll": "stock market chart"},
            {"text": "Fehler drei: Du zahlst hohe Gebühren für Produkte, die du nicht verstehst.", "broll": "signing contract documents"},
            {"text": "Folge für mehr Finanzwissen — den Rest findest du über den Link in der Bio.", "broll": "smartphone social media"},
        ],
        "caption": "Drei Fehler, die dich still und leise Geld kosten 💸\n\n⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung.",
        "hashtags": ["#finanzen", "#geld", "#sparen", "#investieren", "#finanzwissen"],
    })
    stock_analysis = json.dumps({
        "candidates": [
            {
                "ticker": t,
                "chart": ("Der Kurs notiert über 20- und 50-Tage-Linie, die Struktur bleibt aufwärts. "
                          "Der RSI um 55 (Schwungkraft-Maß) zeigt Luft nach oben ohne Überhitzung, keine Empfehlung."),
                "fundamental": ("Mit KGV rund 18 ist die Aktie moderat bewertet (KGV = Preis je Euro Gewinn). "
                                "Das Umsatzplus von 10% und eine Marge von 20% stützen das Geschäft. "
                                "Datenbasierte Einordnung, keine Empfehlung."),
                "overall": ("Chart und Fundamentaldaten stützen sich gegenseitig – ein stimmiges Bild. "
                            "Chance ist die Zielmarke, Risiko der Rückfall unter die Stop-Marke. Keine Empfehlung."),
            }
            for t in ("AAPL", "JPM", "XOM", "SAP.DE", "ALV.DE")
        ],
    })
    feed_post = json.dumps({
        "title": "So wählen wir Aktien für unsere Analysen aus",
        "slides": [
            {"heading": "Wie funktioniert die Auswahl?",
             "body": "Wir kombinieren zwei Blickwinkel: Charttechnik und Fundamentaldaten. "
                     "Jeder Titel bekommt einen Score — ganz ohne Bauchgefühl."},
            {"heading": "Charttechnik",
             "body": "Wir schauen auf den Trend (Kurs über 20- und 50-Tage-Linie) und den RSI, "
                     "ein Maß für die Schwungkraft. Gesund ist ein RSI zwischen 45 und 65."},
            {"heading": "Fundamental",
             "body": "Wir prüfen KGV (wie teuer je Euro Gewinn), Umsatzwachstum und Gewinnmarge. "
                     "Günstig bewertet plus Wachstum ist ein starkes Zeichen."},
            {"heading": "Der Gesamt-Score",
             "body": "50% Charttechnik + 50% Fundamental ergeben eine Ampel: grün, gelb oder rot. "
                     "Wir wählen Titel aus VERSCHIEDENEN Branchen für Streuung."},
            {"heading": "Zusammenfassung",
             "body": "Jeden Tag frische, datenbasierte Einordnungen — folge @rendite.radar.official "
                     "für mehr. Keine Anlageberatung."},
        ],
        "caption": "So läuft unsere Aktien-Auswahl ab — transparent und datenbasiert.\n\n"
                   "Keine Anlageberatung · nur Bildung.",
        "hashtags": ["#finanzen", "#aktien", "#börse", "#investieren", "#charttechnik"],
    })
    trend_ticker = json.dumps(
        {"ticker": "XOM", "name": "Exxon Mobil", "reason": "steht wegen Quartalszahlen im Fokus"}
    )
    return FakeLLM({
        "score_trends": scores, "generate_script": script,
        "stock_analysis": stock_analysis, "feed_post": feed_post,
        "trend_ticker": trend_ticker,
    })


def get_llm() -> LLMProvider:
    if config.LLM_PROVIDER == "fake":
        return builtin_fake()
    return ClaudeProvider()
