"""Generates an educational carousel feed post from a topic via one budget-gated
Claude call (Sonnet). Same JSON-robustness discipline as the stock analyzer
(no inner quotes, strict=False, one retry). Compliance: educational, no advice."""
from __future__ import annotations

import json

from loguru import logger

import config
from src.content.llm import LLMProvider, parse_json_response
from src.content.usage import claude_budget_exceeded
from src.models import FeedPost, Slide

_DISCLAIMER = "Keine Anlageberatung · nur Bildung & Unterhaltung · Werbung"

_BANNED = ("kaufen sie", "jetzt einsteigen", "garantierte rendite", "sicherer gewinn",
           "verdopple dein geld")

_SYSTEM_PROMPT = """Du bist Content-Creator für das deutsche Instagram-Finanz-Bildungsprofil \
"Renditeradar" (Aktien · Analysen · Finanzen). Du schreibst edukative CAROUSEL-Beiträge \
(mehrere Slides) in EINFACHER, motivierender, aber sachlicher Sprache.

STIL:
- Slide 1 = starker Hook (Titel + ein Satz, der neugierig macht).
- Mittlere Slides: je EIN Gedanke, kurze Überschrift + 2–4 knappe Sätze. Konkret, alltagsnah, \
Fachbegriffe in einem Halbsatz erklärt. Gern Zahlen/Beispiele.
- Letzte Slide = kurze Zusammenfassung. Ihre ÜBERSCHRIFT bleibt schlicht (z.B. "Zusammenfassung" \
oder "Kurz gesagt") — NICHT auffordernd wie "Folge uns", denn ein Folgen-Button wird visuell \
ergänzt. Der Folgen-Hinweis darf einmal knapp im Fließtext stehen.
- 5–10 Slides. Bei ausführlichen Schritt-für-Schritt-Anleitungen ruhig 8–10 Slides nutzen und \
je Schritt KONKRET werden (Werkzeuge, Reihenfolge, Fallstricke), damit Leser es nachbauen können.

COMPLIANCE (zwingend, BaFin/MAR):
- KEINE Anlageberatung, KEINE Kauf-/Verkaufsempfehlung für einzelne Wertpapiere.
- Keine Rendite-Versprechen, keine "sicheren" Gewinne. Bei Trading/Echtgeld klar auf RISIKO \
und Verlustmöglichkeit hinweisen.
- Sachlich, edukativ ("So funktioniert…"), nicht direktiv.

WICHTIG für gültiges JSON: in Textwerten KEINE doppelten Anführungszeichen (") und keine \
Zeilenumbrüche. Antworte AUSSCHLIESSLICH mit gültigem JSON, keine Markdown-Umrandung."""

_USER_TEMPLATE = """Erstelle einen edukativen Instagram-Carousel-Beitrag.

Thema: {title}
Inhaltliche Leitplanken: {brief}

Gib genau diese JSON-Struktur zurück:
{{
  "title": "knackiger Titel für Slide 1",
  "slides": [
    {{"heading": "kurze Überschrift", "body": "2-4 knappe, einfache Sätze"}}
  ],
  "caption": "Instagram-Caption (2-4 Zeilen) mit Disclaimer am Ende",
  "hashtags": ["#finanzen", "#aktien", "… 8-12 Stück, deutsch, reichweitenstark"]
}}
Die erste Slide ist der Hook, die letzte Slide die Zusammenfassung. 5-10 Slides — bei \
detaillierten Anleitungen lieber mehr und konkreter."""


def _sanitise(text: str) -> str:
    cleaned = text.strip()
    low = cleaned.lower()
    for bad in _BANNED:
        if bad in low:
            logger.warning(f"Feed-Text enthielt '{bad}' — neutralisiert")
            idx = low.find(bad)
            cleaned = cleaned[:idx] + "so funktioniert" + cleaned[idx + len(bad):]
            low = cleaned.lower()
    return cleaned


def build_feed_post(topic_slug: str, title: str, brief: str, llm: LLMProvider) -> FeedPost | None:
    """One budget-gated Claude call → a FeedPost, or None if unavailable/invalid."""
    if claude_budget_exceeded():
        logger.warning("Claude-Budget erschöpft — kein Feed-Post generiert")
        return None

    user = _USER_TEMPLATE.format(title=title, brief=brief)
    data = None
    for attempt in range(2):
        try:
            raw = llm.complete(
                system=_SYSTEM_PROMPT, user=user,
                model=config.CLAUDE_MODEL, max_tokens=3400, purpose="feed_post",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Feed-Generierung fehlgeschlagen ({exc})")
            return None
        data = parse_json_response(raw)
        if isinstance(data, dict) and data.get("slides"):
            break
        logger.warning(f"Feed-JSON ungültig (Versuch {attempt + 1}/2)")
    if not isinstance(data, dict) or not data.get("slides"):
        return None

    slides = [
        Slide(heading=_sanitise(str(s.get("heading", "")).strip()),
              body=_sanitise(str(s.get("body", "")).strip()))
        for s in data["slides"]
        if isinstance(s, dict) and str(s.get("body", "")).strip()
    ]
    if len(slides) < 3:
        logger.warning("Feed-Post verworfen: weniger als 3 Slides")
        return None

    caption = _sanitise(str(data.get("caption", "")).strip())
    # A tappable @mention of our own profile — the real "link" to follow (feed-post
    # images can't carry a clickable button).
    if config.BRAND_HANDLE and config.BRAND_HANDLE.lower() not in caption.lower():
        caption = f"{caption}\n\nFolge {config.BRAND_HANDLE} für mehr 📈".strip()
    if "anlageberatung" not in caption.lower():
        caption = f"{caption}\n\n⚠️ {_DISCLAIMER}".strip()

    hashtags = [
        h if h.startswith("#") else f"#{h}"
        for h in (str(x).strip() for x in data.get("hashtags", []))
        if h and " " not in h
    ]
    return FeedPost(
        topic_slug=topic_slug,
        title=_sanitise(str(data.get("title", title)).strip()) or title,
        slides=slides[:10],
        caption=caption,
        hashtags=hashtags[:12],
    )
