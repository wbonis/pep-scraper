# pep-scraper

Holt den eigenen PEP-Dienstplan aus P&I LOGA3 (`harzklinikum.pi-asp.de`), schreibt ihn als ICS-Datei
und überträgt ihn auf Wunsch in den Schichtplan einer [Yuvomi](https://github.com/ulsklyc/yuvomi)-Instanz.

Das Tool meldet sich mit einem unsichtbaren Chromium (Playwright) an und liest das JSON, das das Dashboard
selbst von `/loga3/private/api/dashboard/pep/loadShiftsDashboard` lädt (90 Tage im Voraus). Es wird kein
HTML ausgewertet; Sitzung und XSRF-Token verwaltet LOGA selbst.

## Einrichtung

```sh
uv sync
uv run playwright install chromium
cp .env.example .env && chmod 600 .env   # PEP_USERNAME / PEP_PASSWORD eintragen
```

## Aufruf

```sh
uv run pep-scraper              # schreibt ./dienstplan.ics (und überträgt nach Yuvomi, falls eingerichtet)
uv run pep-scraper --dry-run    # Yuvomi-Änderungen nur anzeigen
uv run pep-scraper -v --env-file /pfad/zur/.env
```

### Exit-Codes

| Code | Bedeutung | Was tun |
|---|---|---|
| `0` | alles ok | – |
| `1` | Konfiguration fehlt oder ist falsch | `.env` prüfen |
| `2` | Anmeldung abgelehnt: Kennung/Kennwort falsch, Captcha, 2FA, Zugang gesperrt | Zugangsdaten prüfen, einmal im Browser anmelden |
| `3` | Abruf fehlgeschlagen: Netz, LOGA-Wartung, Dienstplan nicht geladen | meist später erneut versuchen |
| `4` | LOGA liefert ein unbekanntes Format | LOGA wurde vermutlich aktualisiert, Tool anpassen |
| `5` | Übertragung nach Yuvomi fehlgeschlagen | Token, URL, Rechte prüfen |
| `6` | LOGA verlangt ein neues Kennwort | im Browser neues Kennwort vergeben, `PEP_PASSWORD` anpassen |

Bei jedem Fehler bleibt die alte ICS-Datei erhalten. Ein falsches Kennwort und eine LOGA-Wartung werden
sofort erkannt (Text aus der LOGA-Anmeldeseite), ohne das Zeitlimit abzuwarten. Ein abgelaufenes Kennwort
erkennt das Tool daran, dass LOGA nach der Anmeldung ein Kennwortfeld zeigt.

### Namen der Dienste

LOGA liefert nur Codes wie `S006`. Lesbare Namen kommen aus `schichten.toml` (`PEP_NAMES_FILE`, Vorlage:
`schichten.example.toml`). Schlüssel ist der LOGA-Code oder ein Abwesenheitstitel:

```toml
[ZD015]
name = "Früher Spätdienst"
icon = "sunset"

["Fachweiterbildung"]
name = "Schule"
```

Ohne Eintrag gilt eine Faustregel: `F..` Frühdienst, `S..` Spätdienst, `N..` Nachtdienst; sonst bleibt der
Code mit Uhrzeit (`ZD015 11:30-20:00`). Die Namen gelten für die ICS-Datei und für Yuvomi. `schichten.toml`
ist arbeitgeberspezifisch und steht deshalb nicht im Repo. Eigene Pfade für `PEP_NAMES_FILE`,
`PEP_OUTPUT` oder `YUVOMI_STATE_FILE` am besten außerhalb des Repos ablegen.

Ein Abwesenheitstitel in `schichten.toml` gilt im Modus `neutral` als freigegeben und wird in Yuvomi mit
Namen gezeigt – außer es ist ein Gesundheitsgrund. Unbekannte Titel landen als „Abwesend“ mit Hinweis im Log.

### ICS-Datei

- Dienste werden Termine mit Uhrzeit („Nachtdienst“); Nachtdienste enden am Folgetag.
- `00:00-00:00`-Einträge (z. B. `FREI`) und Abwesenheiten (z. B. `Urlaub`, `Fortbildung`) werden ganztägig.
- Die UIDs sind je Tag und Dienst stabil, Kalender-Apps aktualisieren also statt zu verdoppeln.
- Die Datei wird nur für den eigenen Benutzer lesbar angelegt (`0600`).

## Optional: Yuvomi-Schichtplan

Sind `YUVOMI_BASE_URL`, `YUVOMI_API_KEY` und `YUVOMI_USER_ID` gesetzt (siehe `.env.example`), überträgt jeder
Lauf den Dienstplan in den Schichtplan dieses Haushaltsmitglieds. Der Token braucht Schreibrecht auf den
Schichtplan.

- **Schichttypen:** ein Typ je LOGA-Code (Name aus `schichten.toml`, Kürzel = LOGA-Code, Farbe aus LOGA),
  beim ersten Auftreten angelegt. Vorhandene Typen mit gleichem Kürzel oder Namen werden wiederverwendet.
  Ändert sich ein Name oder Icon in `schichten.toml`, benennt der nächste Lauf die eigenen Typen um.
- **Tage:** ein Tageseintrag je Tag; freie Tage werden ausdrücklich als frei eingetragen.
- **Mehrere Dienste an einem Tag:** der erste wird Tageseintrag, weitere werden Zusatzdienste.
- **Abwesenheiten** (`YUVOMI_ABSENCES`):

  | Wert | Wirkung |
  |---|---|
  | `neutral` (Standard) | bekannte harmlose Titel (Urlaub, Fortbildung, Fachweiterbildung, Feiertag, Betrieblich freier Tag, Dienstreise, …) und in `schichten.toml` eingetragene Titel mit Namen; alles andere als „Abwesend“. Gesundheitsgründe (Krank, AU, Kur, Reha, Schwangerschaft, Wiedereingliederung, …) immer als „Abwesend“ |
  | `hidden` | jede Abwesenheit als „Abwesend“ |
  | `detail` | immer mit Titel – zeigt auch Krankmeldungen (Gesundheitsdaten) allen Haushaltsmitgliedern |
  | `skip` | Abwesenheitstage werden nicht eingetragen |
- **Abgleich:** Vom Tool geschriebene Einträge tragen die Notiz `pep-scraper`. Nur diese werden entfernt,
  wenn LOGA einen Tag oder Dienst nicht mehr liefert. Manuelle Einträge an Tagen ohne LOGA-Eintrag bleiben
  unangetastet; an Tagen mit LOGA-Dienst gewinnt LOGA.
- **Aufräumen:** Selbst angelegte Schichttypen merkt sich das Tool in `.pep-scraper-state.json`
  (`YUVOMI_STATE_FILE`) mit Yuvomi-URL und Anlagezeitpunkt. Nutzt LOGA einen davon nicht mehr, wird er
  gelöscht – außer vergangene Tage verweisen noch darauf, dann bleibt er für die Historie stehen. Fremde
  Typen, Typen einer anderen Yuvomi-Instanz und inzwischen veränderte Ids werden nie gelöscht.
- **Mehrfach ausführen** ist unkritisch: ohne Änderung in LOGA schreibt ein Lauf nichts.

## Täglicher Lauf (cron)

```cron
15 6 * * * umask 077; cd /pfad/zu/pi-asp && /opt/homebrew/bin/uv run pep-scraper >> ~/Library/Logs/pep-scraper.log 2>&1
```

`umask 077` hält das Log (enthält Dienstplandaten) für andere Benutzer unlesbar. Der Exit-Code zeigt, ob
der Lauf geklappt hat. Jeder Lauf ist eine echte LOGA-Anmeldung; mehr als ein paar
Läufe am Tag sind nicht nötig und können ein Captcha oder eine Sperre auslösen.

## Entwicklung

```sh
uv run pytest                   # inkl. Browser-Tests gegen ein lokales Fake-LOGA
uv run pytest -m "not browser"  # ohne Chromium
uv run ruff check src tests && uv run mypy src tests && uv run bandit -r src
```

Die GitHub-Actions-CI (`.github/workflows/ci.yml`) führt dieselben Prüfungen bei jedem Push aus.
