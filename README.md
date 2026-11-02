# pep-scraper

Holt den eigenen PEP-Dienstplan aus P&I LOGA3 (z. B. `https://<mandant>.pi-asp.de`), schreibt ihn als ICS-Datei
und überträgt ihn auf Wunsch in den Schichtplan einer [Yuvomi](https://github.com/ulsklyc/yuvomi)-Instanz.

Das Tool meldet sich mit einem unsichtbaren Chromium (Playwright) an und liest das JSON, das das Dashboard
selbst von `/loga3/private/api/dashboard/pep/loadShiftsDashboard` lädt (90 Tage im Voraus). Es wird kein
HTML ausgewertet; Sitzung und XSRF-Token verwaltet LOGA selbst.

## Einrichtung

```sh
uv sync
uv run playwright install chromium
cp .env.example .env && chmod 600 .env   # PEP_BASE_URL, PEP_USERNAME, PEP_PASSWORD eintragen
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
Code mit Uhrzeit (`ZD015 11:30-20:00`). Die Namen gelten für die ICS-Datei und für Yuvomi.

**Neue Codes werden automatisch eingetragen:** Liefert LOGA einen Dienstcode, der noch nicht in
`schichten.toml` steht, hängt das Tool ihn mit dem bisherigen Namen ans Dateiende an (die Datei wird bei
Bedarf angelegt). Vorhandener Inhalt und Kommentare bleiben unverändert; den Namen danach einfach anpassen.
Abwesenheitstitel werden nie automatisch eingetragen, weil ein eingetragener Titel in Yuvomi sichtbar wird.
Aus demselben Grund fehlen Codes, die wie ein Abwesenheitstitel oder ein Gesundheitsgrund lauten, sowie Codes
mit Steuerzeichen. Ein Symlink auf `schichten.toml` bleibt erhalten, die Dateirechte auch. Würde die Datei
danach nicht mehr lesbar sein, schreibt das Tool nichts und meldet nur eine Warnung.
`--dry-run` trägt nichts ein; abschalten mit `neue_codes_eintragen = false`. `schichten.toml`
ist arbeitgeberspezifisch und steht deshalb nicht im Repo. Eigene Pfade für `PEP_NAMES_FILE`,
`PEP_OUTPUT` oder `YUVOMI_STATE_FILE` am besten außerhalb des Repos ablegen.

### Einstellungen (`[einstellungen]` in `schichten.toml`)

Schalter stehen im Abschnitt `[einstellungen]` derselben Datei. Alles ist optional; ohne Abschnitt gelten
die Standardwerte. Ein unbekannter Schlüssel oder falscher Wert bricht mit Exit-Code `1` ab, bevor sich
das Tool bei LOGA anmeldet.

```toml
[einstellungen]
# Feiertagsregel
feiertagsregel = true                 # Standard: true
feiertage = ["Feiertag", "Feiertage", "Betrieblich freier Tag"]   # Standard

# Neue Dienstcodes automatisch eintragen
neue_codes_eintragen = true           # Standard: true

# Arbeitszeitäquivalent: Gutschrift für ganztägige Einträge
gutschrift = ["Urlaub", "Fortbildung"]   # Standard: [] = aus
gutschrift_modus = "termin"           # termin | info
schicht_start = "08:00"               # Beginn der Gutschrift, Standard 08:00
stunden_pro_tag = 8                   # oder: stunden_pro_woche = 40 (÷ 5 Tage)

# Pausenabzug
pause_minuten = 30                    # Standard: 0 = aus
pause_ab_stunden = 6                  # nur Dienste länger als 6 Std., Standard 0 = alle
pause_modus = "kuerzen"               # kuerzen | info
```

- **Feiertagsregel:** Ein Feiertag oder betrieblich freier Tag ohne Dienst am selben Tag erscheint als
  „Freier Tag“ (ICS ganztägig, Yuvomi als frei; der LOGA-Titel steht in der Beschreibung). Gibt es an dem
  Tag einen Dienst, wird der Feiertag weggelassen und nur der Dienst übernommen. Ohne die Regel gewinnt
  in Yuvomi die Abwesenheit, der Dienst fehlt dort dann. Vergleich ohne Groß-/Kleinschreibung. Mit
  `feiertage = [...]` lassen sich die Titel anpassen. Wer „Freier Tag“ anders nennen will, trägt den
  LOGA-Titel in `schichten.toml` ein (z. B. `["Feiertag"]` mit `name = "Feiertag (frei)"`).
- **Gutschrift** (Arbeitszeitäquivalent) gilt für ganztägige Einträge, deren LOGA-Titel oder Code in
  `gutschrift` steht:
  - `termin`: Aus dem Eintrag wird ein Termin mit Uhrzeit ab `schicht_start`, z. B. Urlaub 08:00–16:00. Das
    gilt in ICS und Yuvomi; in Yuvomi bekommt der Schichttyp die Uhrzeit. Ist der Titel in Yuvomi als
    „Abwesend“ verborgen, bleibt der gemeinsame Typ ohne Uhrzeit.
  - `info`: Der Eintrag bleibt ganztägig, die ICS-Beschreibung bekommt „Gutschrift 8:00 Std.“.
  - `stunden_pro_woche` wird durch 5 Arbeitstage geteilt (39 → 7:48 Std.). Kommazahlen sind erlaubt
    (`stunden_pro_tag = 7.7`). Nur eins von beiden angeben.
- **Pausenabzug** gilt nur für Dienste mit Uhrzeit, nicht für freie Tage und Gutschriften. Abgezogen wird nur,
  wenn der Dienst länger als `pause_ab_stunden` dauert (`6` entspricht § 4 ArbZG) und länger als die Pause ist:
  - `kuerzen`: Die Pause geht vom Dienstende ab, aus 13:45–22:15 wird 13:45–21:45. Achtung: Kalender und
    Yuvomi zeigen dann nicht mehr das echte Dienstende. In Yuvomi werden eigene Schichttypen auf die neue
    Uhrzeit umgestellt; fremde Typen bleiben unverändert.
  - `info`: Die Uhrzeit bleibt, die ICS-Beschreibung bekommt „Netto 8:00 Std.“.

Reihenfolge: zuerst Feiertagsregel, dann Gutschrift, dann Pausenabzug, zuletzt die Namen.

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
  Ändert sich ein Name oder Icon in `schichten.toml` oder eine Uhrzeit (z. B. durch den Pausenabzug), passt
  der nächste Lauf die eigenen Typen an.
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
