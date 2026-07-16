# Phase 0 — Setup-Anleitung (manuelle Schritte)

Diese Schritte kann nur der Betreiber selbst erledigen. Reihenfolge beachten —
die Affiliate-Anmeldungen (Schritt 5) haben Prüf-Vorlauf, daher früh starten.

## 1. Instagram-Profil anlegen

1. Neues Instagram-Konto erstellen (App oder Web). Handle-Kriterien: kurz, merkbar,
   Finanz-Bezug, ohne Zahlen/Unterstriche wenn möglich (z. B. `klargeld.daily`,
   `finanzblick.de`, `geldwissen.reels` — Verfügbarkeit prüfen).
2. Profil einrichten: Profilbild (einfaches Logo/Icon, hoher Kontrast), Bio mit
   Nutzenversprechen ("Täglich Finanzwissen in 45 Sekunden") + Platz für den Link.
3. **In ein Professional-Konto umwandeln:** Einstellungen → Konto → "Zu professionellem
   Konto wechseln" → **Creator** oder **Business** (Business empfohlen für die API).
4. **Facebook-Seite erstellen und verknüpfen** (Voraussetzung für die Graph API):
   facebook.com → Seite erstellen (gleicher Name) → dann in Instagram:
   Einstellungen → Konto-Center bzw. "Verknüpfte Konten" → Facebook-Seite verbinden.

## 2. Meta-Developer-App + API-Zugang

1. https://developers.facebook.com → "Meine Apps" → App erstellen → Typ **Business**.
2. Produkt **Instagram** bzw. "Instagram Graph API" hinzufügen.
3. Im **Graph API Explorer** (Tools): App auswählen, User-Token generieren mit den
   Berechtigungen `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`,
   `pages_show_list`, `pages_read_engagement`.
4. Kurzlebigen Token in einen **Long-lived Token** (60 Tage) tauschen:
   `GET /oauth/access_token?grant_type=fb_exchange_token&client_id={app-id}&client_secret={app-secret}&fb_exchange_token={token}`
5. **IG-User-ID ermitteln:** `GET /me/accounts` → Page-ID → `GET /{page-id}?fields=instagram_business_account`.
6. In `.env` eintragen: `IG_ACCESS_TOKEN`, `IG_USER_ID`, `FB_APP_ID`, `FB_APP_SECRET`.

> Solange nur das eigene Konto (mit App-Rolle) bespielt wird, reicht der
> Entwicklermodus — kein App-Review nötig.

## 3. Dienste-Accounts

| Dienst | Wo | .env-Schlüssel | Kosten |
|---|---|---|---|
| ElevenLabs | elevenlabs.io → Profil → API Key; deutsche Stimme in der Voice Library wählen, Voice-ID kopieren | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Starter ~5 $/Monat |
| Pexels | pexels.com/api → Key beantragen | `PEXELS_API_KEY` | kostenlos |
| Telegram | @BotFather → `/newbot`; danach dem Bot schreiben und die Chat-ID via `https://api.telegram.org/bot<TOKEN>/getUpdates` auslesen | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | kostenlos |
| Reddit | reddit.com/prefs/apps → "script"-App anlegen | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | kostenlos |
| Anthropic | console.anthropic.com (vorhandener Account vom Trading-Bot nutzbar) | `ANTHROPIC_API_KEY` | budget-gedeckelt |

## 4. Musik-Pool füllen

2–5 lizenzfreie Tracks (ruhig/spannungsvoll, ohne Vocals) nach `assets/music/` legen —
Quellen und Lizenzhinweise siehe `assets/music/README.md`.

## 5. Affiliate-Anmeldungen (Vorlauf!)

1. **financeAds** (financeads.net) — größtes deutsches Finanz-Affiliate-Netzwerk
   (Broker, Depots, Kredite). Anmeldung als Publisher mit dem Instagram-Profil.
2. **Awin** (awin.com) — dort laufen weitere Broker-/Finanzprogramme.
3. Hinweis: Manche Programme verlangen existierende Reichweite — ggf. nach 4–6 Wochen
   Content-Aufbau erneut bewerben. Monetarisierung ist ohnehin erst Phase 4.

## 6. Server-Deployment (Phase 2)

1. Repo auf den Hetzner-Server klonen (analog trading-bot: `git pull` unter `/opt/`).
2. `python -m venv venv && venv/bin/pip install -r requirements.txt`; ffmpeg: `apt install ffmpeg`.
3. nginx-Location für `PUBLIC_MEDIA_DIR` (z. B. `/var/www/reels` → `https://<domain>/reels/`),
   Verzeichnislisting deaktiviert.
4. systemd-Service für `python main.py run` (Vorlage vom Trading-Bot übernehmen).

## Kennzeichnungspflichten (Betrieb)

- Affiliate-Posts/Bio als **Werbung** kennzeichnen (z. B. "Werbung | Affiliate-Links").
- Der Disclaimer "Keine Anlageberatung" wird vom Script-Agent erzwungen — beim Review
  trotzdem prüfen.
- Impressumspflicht: Landing-Page (Phase 4) braucht ein Impressum; bis dahin genügt
  ein Impressums-Link in der Bio, sobald das Profil geschäftsmäßig betrieben wird.
