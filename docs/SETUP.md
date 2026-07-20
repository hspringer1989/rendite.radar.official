# Phase 0 — Setup-Anleitung (manuelle Schritte)

Diese Schritte kann nur der Betreiber selbst erledigen. Reihenfolge beachten —
die Affiliate-Anmeldungen (Schritt 5) haben Prüf-Vorlauf, daher früh starten.

## 1. Instagram-Profil anlegen

1. Neues Instagram-Konto erstellen (App: "Konto hinzufügen" → "Neues Konto erstellen",
   eigene E-Mail-Adresse verwenden). **Handle-Verfügbarkeit nur über das
   Username-Feld im Registrierungsdialog prüfen** — Google-/Web-Suchen liefern
   False Negatives.
2. Profil einrichten: Profilbild (einfaches Logo/Icon, hoher Kontrast), Bio mit
   Nutzenversprechen ("Täglich Finanzwissen in 45 Sekunden") + Platz für den Link.
3. **In ein Professional-Konto umwandeln:** Einstellungen → Konto → "Zu professionellem
   Konto wechseln" → **Creator** genügt (Business geht auch). Eine Facebook-Seite ist
   mit dem empfohlenen API-Weg (Instagram-Login) NICHT nötig.

## 2. Meta-Developer-App + API-Zugang (Instagram-Login-Variante, empfohlen)

0. **Voraussetzung — einmalige Developer-Registrierung** (sonst fehlt "Meine Apps"):
   Auf developers.facebook.com mit dem persönlichen Facebook-Konto einloggen
   (Portal-Login läuft über Facebook; eine Facebook-*Seite* bleibt trotzdem unnötig),
   dann über https://developers.facebook.com/async/registration registrieren:
   Bedingungen akzeptieren → E-Mail + Telefon per Code bestätigen → Beruf wählen.
1. "Meine Apps" (oben rechts, oder direkt https://developers.facebook.com/apps/creation/)
   → App erstellen → App-Name + Kontakt-E-Mail → Use case **"Instagram"** wählen
   (Wortlaut variiert, z. B. "Verwalte Nachrichten und Inhalte auf Instagram");
   Business-Portfolio-Verknüpfung kann übersprungen werden.
2. In der App unter **Instagram → API setup with Instagram business login**:
   das RenditeRebell-Konto als Instagram-Tester/Konto hinzufügen und autorisieren
   (Berechtigungen `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_insights`).
3. Dort direkt den **Access Token generieren** (long-lived, 60 Tage) und die
   angezeigte **Instagram-User-ID** kopieren.
4. In `.env` eintragen: `IG_ACCESS_TOKEN`, `IG_USER_ID`
   (`GRAPH_BASE_URL` bleibt auf dem Default `https://graph.instagram.com`).
5. Token-Verlängerung: `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=...`
   (macht `refresh_long_lived_token()` in `src/publish/instagram.py`).

> Solange nur das eigene Konto (mit App-Rolle/Tester) bespielt wird, reicht der
> Entwicklermodus — kein App-Review nötig.
>
> Alternative (klassische Facebook-Login-Variante mit verknüpfter Facebook-Seite):
> `GRAPH_BASE_URL=https://graph.facebook.com` + `FB_APP_ID`/`FB_APP_SECRET` setzen;
> Berechtigungen dann `instagram_basic`, `instagram_content_publish`,
> `instagram_manage_insights`, `pages_show_list`.

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
