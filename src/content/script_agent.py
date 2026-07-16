"""Generates the German reel script (Sonnet): hook-first structure, retention
pacing, CTA — with the compliance rules hard-wired into the system prompt."""
from loguru import logger

import config
from src.content.llm import LLMProvider, parse_json_response
from src.models import ReelScript, ScriptSegment, TrendItem

# German speech pace ≈ 2.4 words/second — keeps the voiceover inside the target length
_WORDS_PER_SECOND = 2.4

_DISCLAIMER = "⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung."

_SYSTEM_PROMPT = """Du schreibst Voiceover-Skripte für virale deutsche Instagram-Reels \
eines Finanz-/Investing-Profils. Zielgruppe: 20–45, DACH, finanzinteressiert.

Struktur (Retention-optimiert):
1. HOOK (erstes Segment, max. 12 Wörter): Schock, Frage oder kontraintuitive Aussage — \
muss in 2 Sekunden Aufmerksamkeit erzwingen ("Diese 3 Fehler kosten dich 100.000 €...")
2. 3–5 kurze Segmente: ein Gedanke pro Segment, einfache Sprache, konkrete Zahlen, \
direkte Ansprache ("du")
3. CTA am Ende: "Folge {brand} für deinen täglichen Finanzhappen" (Wortlaut variieren) + \
"Mehr dazu über den Link in der Bio" (nur wenn thematisch passend)

COMPLIANCE (zwingend, keine Ausnahmen):
- KEINE Anlageberatung, KEINE Kauf-/Verkaufsempfehlung für einzelne Aktien/Coins
- Formuliere edukativ/newsbezogen ("Was hinter X steckt"), nicht direktiv ("Kauf jetzt X")
- Keine Rendite-Versprechen, keine "sicheren" Gewinne
- Die Caption endet mit dem Disclaimer "{disclaimer}"

Für jedes Segment gib ENGLISCHE Stock-Footage-Suchbegriffe an (2–4 Wörter, visuell konkret, \
z. B. "stock market chart red", "person counting euro bills").

Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt, kein Fließtext, keine Markdown-Umrandung."""

_USER_TEMPLATE = """Schreibe ein Reel-Skript zu diesem Trend-Thema:

Thema: {title}
Kontext: {summary}
Quelle: {source}

Ziellänge gesprochen: ~{target_words} Wörter (≈ {target_seconds} Sekunden).

Gib genau diese JSON-Struktur zurück:
{{
  "title": "interner Arbeitstitel",
  "segments": [
    {{"text": "Hook-Satz auf Deutsch", "broll": "english footage keywords"}},
    {{"text": "…", "broll": "…"}}
  ],
  "caption": "Instagram-Caption auf Deutsch, 2-4 Zeilen, mit Disclaimer am Ende",
  "hashtags": ["#finanzen", "#geld", "…  (8-12 Stück, deutsch+reichweitenstark)"]
}}"""


def generate_script(trend: TrendItem, llm: LLMProvider) -> ReelScript | None:
    target_words = int(config.REEL_TARGET_SECONDS * _WORDS_PER_SECOND)
    raw = llm.complete(
        system=_SYSTEM_PROMPT.format(disclaimer=_DISCLAIMER, brand=config.BRAND_NAME),
        user=_USER_TEMPLATE.format(
            title=trend.title,
            summary=trend.summary or "(kein weiterer Kontext)",
            source=trend.source,
            target_words=target_words,
            target_seconds=config.REEL_TARGET_SECONDS,
        ),
        model=config.CLAUDE_MODEL,
        max_tokens=1500,
        purpose="generate_script",
    )
    data = parse_json_response(raw)
    if not isinstance(data, dict):
        return None

    try:
        segments = [
            ScriptSegment(text=str(s["text"]).strip(), broll_query=str(s.get("broll", "")).strip())
            for s in data["segments"]
            if str(s.get("text", "")).strip()
        ]
    except (KeyError, TypeError):
        logger.warning("Skript verworfen: 'segments' fehlt oder ist fehlerhaft")
        return None
    if len(segments) < 2:
        logger.warning("Skript verworfen: weniger als 2 Segmente")
        return None

    caption = str(data.get("caption", "")).strip()
    # Compliance safety net: the disclaimer must survive even a sloppy model response
    if "anlageberatung" not in caption.lower():
        caption = f"{caption}\n\n{_DISCLAIMER}".strip()

    hashtags = [
        h if h.startswith("#") else f"#{h}"
        for h in (str(x).strip() for x in data.get("hashtags", []))
        if h and " " not in h
    ]

    return ReelScript(
        hook=segments[0].text,
        segments=segments,
        caption=caption,
        hashtags=hashtags[:15],
        title=str(data.get("title", trend.title))[:120],
    )
