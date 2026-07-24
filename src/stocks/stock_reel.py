"""A stock-analysis REEL (video): the same chart+fundamental+traffic-light substance
as the daily story cards, but as a 1080×1920 voiceover reel. Three branded full-screen
frames (Charttechnik with the drawn chart + risk marks, Fundamental key figures,
Gesamtbild with both traffic lights) are used as segment backgrounds, book-ended by
Pexels b-roll for the hook and CTA. Educational/watchlist framing only (BaFin/MAR)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

import config
from src.content.llm import LLMProvider, get_llm, parse_json_response
from src.content.usage import claude_budget_exceeded
from src.models import Candidate, ReelScript, ScriptSegment
from src.render.broll import PexelsBroll
from src.render.renderer import pick_music, render_reel
from src.stocks import indicators as ind
from src.stocks import story_cards as sc
from src.stocks.analyzer import _sanitise, build_candidate_for_ticker
from src.stocks.market_data import MarketData, get_market_data
from src.storage.database import ReelRow, session_scope
from src import branding

_font = branding.load_font
W, H = 1080, 1920

_DISCLAIMER = "⚠️ Keine Anlageberatung — nur Bildung & Unterhaltung. Kein Kauf-/Verkaufsaufruf."

_HOOK_QUERY = "artificial intelligence computer chip"
_CTA_QUERY = "young person investing smartphone"

# Currency codes → spoken German (so the voice says "US-Dollar", not the letters "U-S-D").
_CURRENCY_SPOKEN = {
    "USD": "US-Dollar", "EUR": "Euro", "GBP": "britische Pfund", "CHF": "Franken",
    "SEK": "schwedische Kronen", "DKK": "dänische Kronen", "NOK": "norwegische Kronen",
    "JPY": "Yen",
}


def _spoken_name(name: str) -> str:
    """A voice-friendly company name: first significant token, all-caps de-shouted
    (NVIDIA → Nvidia) so ElevenLabs says the name instead of spelling letters. Short
    acronyms (SAP, IBM, AMD) are kept as letters on purpose."""
    base = re.split(r"[ ,.]", name.strip())[0] or name.strip()
    if base.isupper() and len(base) > 4:
        return base.capitalize()
    return base


def _spoken_de(text: str, ticker: str, name: str) -> str:
    """Normalise a segment's text for natural German TTS WITHOUT changing meaning:
    ticker/all-caps name → spoken name, currency codes/symbols → words, and decimal
    commas get the spoken word 'Komma' so the voice doesn't pause mid-number."""
    spoken = _spoken_name(name)
    for token in {ticker, ticker.split(".")[0], name.split()[0] if name else ""}:
        if token:
            text = re.sub(rf"\b{re.escape(token)}\b", spoken, text)
    for code, word in _CURRENCY_SPOKEN.items():
        text = re.sub(rf"\b{code}\b", word, text)
    text = text.replace("$", " Dollar").replace("€", " Euro").replace("%", " Prozent")
    text = re.sub(r"(\d+),(\d+)", r"\1 Komma \2", text)          # 209,38 → "209 Komma 38"
    text = re.sub(r"(\d+)\.(\d{1,2})\b", r"\1 Komma \2", text)   # score 0.72 → "0 Komma 72"
    return re.sub(r"\s+", " ", text).strip()


# ── branded full-screen frames (content in the top ~1080px, lower band left clear
#    for the karaoke subtitles the renderer burns in) ─────────────────────────────
def _base():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), branding.BG)
    d = ImageDraw.Draw(img)
    d.line((60, H - 120, W - 60, H - 120), fill=branding.MUTED, width=2)
    d.text((60, H - 104), "Keine Anlageberatung · keine Kauf-/Verkaufsempfehlung · Werbung",
           font=_font(24), fill=branding.MUTED)
    return img, d


def _head(d, kicker: str, m, ampel_label: str, level: str) -> None:
    kf = _font(30, bold=True)
    kw = d.textlength(kicker, font=kf)
    d.rounded_rectangle((60, 120, 60 + kw + 44, 178), radius=14, fill=branding.BLUE)
    d.text((82, 130), kicker, font=kf, fill=(255, 255, 255))
    x = branding.market_badge(d, 60, 214, m.market)
    d.text((x, 190), m.ticker, font=_font(66, bold=True), fill=branding.FG)
    d.text((60, 292), m.name[:28], font=_font(34), fill=branding.MUTED)
    r, cy = 24, 390
    d.ellipse((60, cy - r, 60 + 2 * r, cy + r), fill=branding.LIGHT.get(level, branding.MUTED))
    d.text((60 + 2 * r + 20, cy - r + 4), ampel_label, font=_font(42, bold=True), fill=branding.FG)


def render_reel_chart_frame(c: Candidate, out_path: str) -> str:
    m = c.metrics
    img, d = _base()
    lvl, lab = ind.tendency(m.tech_score, "chart")
    _head(d, "CHART-CHECK", m, f"Charttechnik: {lab}", lvl)
    sc._draw_chart(d, (60, 452, W - 60, 1050), m.history_closes,
                   c.stop_loss, c.take_profit, c.entry, m.currency)
    d.text((60, 1075), f"Stop {c.stop_loss:.0f} {m.currency}    ·    Ziel {c.take_profit:.0f} {m.currency}",
           font=_font(36, bold=True), fill=branding.FG)
    d.text((60, 1126), "charttechnische Marken (ATR-basiert) — keine Empfehlung",
           font=_font(26), fill=branding.MUTED)
    return sc._save(img, out_path)


def render_reel_fundamental_frame(c: Candidate, out_path: str) -> str:
    m = c.metrics
    img, d = _base()
    lvl, lab = ind.tendency(m.fund_score, "fund")
    _head(d, "FUNDAMENTAL-CHECK", m, f"Fundamental: {lab}", lvl)
    y = 470
    d.rounded_rectangle((60, y, W - 60, y + 560), radius=28, fill=branding.CARD)
    rows = [
        ("KGV (Preis je € Jahresgewinn)", sc._fig(m.pe)),
        ("Umsatzwachstum", sc._fig(m.revenue_growth, pct=True)),
        ("Gewinnmarge", sc._fig(m.profit_margin, pct=True)),
        ("Fundamental-Score (0–1)", f"{m.fund_score:.2f}".replace(".", ",")),
    ]
    yy = y + 40
    for label, val in rows:
        d.text((100, yy), label, font=_font(34), fill=branding.MUTED)
        d.text((100, yy + 48), val, font=_font(58, bold=True), fill=branding.FG)
        yy += 130
    return sc._save(img, out_path)


def render_reel_overall_frame(c: Candidate, out_path: str) -> str:
    m = c.metrics
    img, d = _base()
    olvl, olab = ind.tendency(m.blended, "overall")
    _head(d, "GESAMTBILD", m, f"Gesamtbild: {olab}", olvl)
    y = 490
    d.rounded_rectangle((60, y, W - 60, y + 340), radius=28, fill=branding.CARD)
    clvl, clab = ind.tendency(m.tech_score, "chart")
    flvl, flab = ind.tendency(m.fund_score, "fund")
    for i, (label, lv) in enumerate(((f"Charttechnik — {clab}", clvl),
                                     (f"Fundamental — {flab}", flvl))):
        yy = y + 56 + i * 150
        r = 26
        d.ellipse((100, yy, 100 + 2 * r, yy + 2 * r), fill=branding.LIGHT.get(lv, branding.MUTED))
        d.text((100 + 2 * r + 26, yy + 4), label, font=_font(46, bold=True), fill=branding.FG)
    return sc._save(img, out_path)


# ── spoken script (5 fixed roles matching the visuals above) ─────────────────
_ROLES = ("hook", "chart", "fundamental", "overall", "cta")

_SYS = """Du schreibst das deutsche VOICEOVER-Skript für ein virales Instagram-Reel eines \
Finanz-Bildungsprofils (Renditeradar). Zielgruppe: fortgeschrittene Privatanleger im DACH-Raum.

Aufbau (fünf kurze, gesprochene Segmente, je auf seine Rolle zugeschnitten):
- hook: max. 12 Wörter, erzeugt sofort Spannung/Neugier zur Aktie und zum aktuellen Aufreger.
- chart: 1–2 Sätze zur Charttechnik. Nenne KONKRET Kurs vs. 20-/50-Tage-Linie (Trend) und RSI, \
und erwähne die charttechnischen Marken (Stop/Ziel) als Orientierung — nicht als Handlung.
- fundamental: 1–2 Sätze mit KGV (teuer/günstig), Umsatzwachstum, Gewinnmarge — was das heißt.
- overall: 1–2 Sätze: passen Chart und Fundamental zusammen? Wichtigste Chance UND wichtigstes Risiko.
- cta: max. 10 Wörter, natürliche gesprochene Einladung zum Folgen (locker, kein \
Werbe-Ton, kein Rendite-Versprechen). Beispiel-Ton: "Wenn dich das interessiert, folg uns gern."

STRIKTE COMPLIANCE (BaFin/MAR): beobachtend, KEINE Kauf-/Verkaufsempfehlung, keine \
Rendite-Versprechen, keine Imperative wie "kaufen"/"einsteigen". Ampel und Marken beschreiben \
die DATEN, nicht eine Handlung.

DAS SKRIPT WIRD VORGELESEN — schreibe alles so, wie es natürlich gesprochen klingt:
- Nutze den FIRMENNAMEN (z. B. "Nvidia"), NIEMALS das Kürzel/Ticker (nicht "NVDA").
- Währung ausgeschrieben: "US-Dollar" / "Euro" — niemals "USD", "$", "€".
- RUNDE Zahlen im Text (keine Nachkommastellen): "rund 209 US-Dollar", nicht "209,38".
- "Prozent" ausschreiben statt "%".
- Jedes Segment kurz halten (die 5 Segmente zusammen ca. 45–55 Sekunden gesprochen).

SPRACHE: natürliche gesprochene Sätze, korrekte deutsche Umlaute, NIEMALS ae/ue/oe/ss-Ersatz.
WICHTIG für gültiges JSON: keine doppelten Anführungszeichen und keine Zeilenumbrüche innerhalb der Textwerte.
Antworte AUSSCHLIESSLICH mit gültigem JSON, kein Fließtext, keine Markdown-Umrandung."""

_USER = """Erstelle das Reel-Skript für diese Aktie. Nutze die echten Zahlen und interpretiere sie.

Aktueller Aufhänger (Aufreger): {topic}

Daten:
{payload}

Gib GENAU diese JSON-Struktur zurück:
{{
  "hook": "...",
  "chart": "...",
  "fundamental": "...",
  "overall": "...",
  "cta": "...",
  "caption": "Instagram-Caption, 2–3 Zeilen, mit Disclaimer am Ende",
  "hashtags": ["#aktien", "#börse", "... 8–12 deutsche, reichweitenstarke Tags"]
}}"""


def _fallback(c: Candidate, topic: str) -> tuple[dict, str, list[str]]:
    m = c.metrics
    name = _spoken_name(m.name)
    texts = {
        "hook": f"{name} — alle reden drüber. Aber was sagen die Daten wirklich?",
        "chart": c.chart_text or "",
        "fundamental": c.fundamental_text or "",
        "overall": c.overall_text or "",
        "cta": "Wenn dich solche Analysen interessieren, folg uns einfach für mehr.",
    }
    texts["chart"] = (texts["chart"] + f" Charttechnisch liegt die Risikomarke bei rund "
                      f"{c.stop_loss:.0f} und die Potenzialmarke bei rund {c.take_profit:.0f} "
                      f"{m.currency}.").strip()
    caption = (f"{m.name}: {topic}. Was Charttechnik und Fundamental aktuell zeigen — mit unserem "
               f"Ampel-Check.\n\nFolge {config.BRAND_HANDLE} für mehr 📈\n\n{_DISCLAIMER}")
    hashtags = ["#aktien", "#börse", "#investieren", "#finanzen", "#charttechnik",
                "#fundamentalanalyse", "#" + m.ticker.lower().replace(".", ""), "#geldanlage"]
    return texts, caption, hashtags


def _reel_script(c: Candidate, llm: LLMProvider, topic: str) -> tuple[dict, str, list[str]]:
    if claude_budget_exceeded():
        logger.warning("Claude-Budget erschöpft — regelbasiertes Reel-Skript")
        return _fallback(c, topic)
    m = c.metrics
    payload = json.dumps({
        "ticker": m.ticker, "name": m.name, "sector": m.sector,
        "price": m.price, "currency": m.currency, "sma20": m.sma20, "sma50": m.sma50,
        "rsi": m.rsi, "pe": m.pe, "revenue_growth": m.revenue_growth,
        "profit_margin": m.profit_margin, "stop_mark": round(c.stop_loss),
        "target_mark": round(c.take_profit),
        "chart_ampel": ind.tendency(m.tech_score, "chart")[1],
        "fundamental_ampel": ind.tendency(m.fund_score, "fund")[1],
        "gesamt_ampel": ind.tendency(m.blended, "overall")[1],
    }, ensure_ascii=False)
    try:
        raw = llm.complete(system=_SYS, user=_USER.format(topic=topic, payload=payload),
                           model=config.CLAUDE_MODEL, max_tokens=1400, purpose="stock_reel")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Reel-Skript-LLM fehlgeschlagen ({exc}) — regelbasiert")
        return _fallback(c, topic)
    data = parse_json_response(raw)
    if not isinstance(data, dict) or not all(data.get(k) for k in _ROLES):
        logger.warning("Reel-Skript-JSON unvollständig — regelbasiert")
        return _fallback(c, topic)

    fb_texts, fb_caption, fb_tags = _fallback(c, topic)
    texts = {k: _sanitise(str(data.get(k, "")).strip()) or fb_texts[k] for k in _ROLES}
    caption = str(data.get("caption", "")).strip() or fb_caption
    if "anlageberatung" not in caption.lower():
        caption = f"{caption}\n\n{_DISCLAIMER}"
    tags = [t if t.startswith("#") else f"#{t}"
            for t in (str(x).strip() for x in data.get("hashtags", [])) if t and " " not in t]
    return texts, caption, (tags[:12] or fb_tags)


def build_stock_reel(ticker: str, topic: str = "", md: MarketData | None = None,
                     llm: LLMProvider | None = None) -> int | None:
    """Analyse one ticker → 5-segment voiceover reel with the chart/fundamental/overall
    frames as backgrounds. Persists a ReelRow(pending_review); returns its id or None."""
    md = md or get_market_data()
    llm = llm or get_llm()
    topic = topic or "aktuell stark im Gespräch"
    c = build_candidate_for_ticker(md, ticker.upper(), llm)
    if c is None:
        logger.warning(f"{ticker}: keine Daten — kein Reel")
        return None

    texts, caption, hashtags = _reel_script(c, llm, topic)
    # normalise each segment for natural TTS (ticker→name, USD→US-Dollar, decimals→"Komma");
    # done per-segment so the burned-in subtitles stay in sync with the spoken words.
    texts = {k: _spoken_de(v, ticker.upper(), c.metrics.name) for k, v in texts.items()}
    segments = [ScriptSegment(text=texts[r], broll_query="") for r in _ROLES]
    script = ReelScript(hook=texts["hook"], segments=segments, caption=caption,
                        hashtags=hashtags, title=f"{c.metrics.name} — Analyse-Reel")

    with session_scope() as session:
        reel = ReelRow(trend_id=0,
                       script_json=json.dumps({"ticker": ticker, "texts": texts}, ensure_ascii=False),
                       caption=f"{caption}\n\n{' '.join(hashtags)}".strip(), status="draft")
        session.add(reel)
        session.flush()
        reel_id = reel.id

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = Path(config.OUTPUT_DIR) / f"reel_{reel_id}_{stamp}"
    try:
        from src.tts.base import get_tts

        tts = get_tts().synthesize(script.full_text, base.with_suffix(".mp3"))
        chart_img = render_reel_chart_frame(c, f"{base}_chart.jpg")
        fund_img = render_reel_fundamental_frame(c, f"{base}_fund.jpg")
        over_img = render_reel_overall_frame(c, f"{base}_over.jpg")
        broll = PexelsBroll()
        paths = [broll.fetch(_HOOK_QUERY, 2.0), chart_img, fund_img, over_img,
                 broll.fetch(_CTA_QUERY, 2.0)]
        video = render_reel(script, tts, paths, base.with_suffix(".mp4"), pick_music())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Aktien-Reel #{reel_id} fehlgeschlagen: {exc}")
        with session_scope() as session:
            row = session.get(ReelRow, reel_id)
            row.status, row.error = "failed", str(exc)[:2000]
        return None

    with session_scope() as session:
        row = session.get(ReelRow, reel_id)
        row.audio_path = tts.audio_path
        row.video_path = str(video)
        row.status = "pending_review"
    logger.info(f"Aktien-Reel #{reel_id} ({ticker}) fertig: {video}")
    return reel_id
