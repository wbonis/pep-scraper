# Changelog

Alle nennenswerten Änderungen an diesem Projekt. Format nach
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt
- Dependabot hält Python-Abhängigkeiten (`uv`) und GitHub Actions wöchentlich aktuell.
- Dieses Changelog.

## [0.1.0] – 2026-11-02

Erste Version.

### Hinzugefügt
- **LOGA3-Abruf:** Anmeldung mit unsichtbarem Chromium (Playwright). Der Dienstplan kommt aus dem JSON, das
  das Dashboard selbst lädt (`pep/loadShiftsDashboard`, 90 Tage im Voraus); Sitzung und XSRF-Token verwaltet
  LOGA selbst.
- **ICS-Export:** Dienste als Termine mit Uhrzeit, Nachtdienste enden am Folgetag, freie Tage und
  Abwesenheiten ganztägig. Stabile UIDs, damit Kalender-Apps aktualisieren statt zu verdoppeln. Datei mit
  Rechten `0600`, atomar geschrieben.
- **Yuvomi-Schichtplan (optional):** Übertragung des Dienstplans in den Schichtplan eines
  Haushaltsmitglieds (`YUVOMI_BASE_URL`, `YUVOMI_API_KEY`, `YUVOMI_USER_ID`).
  - Ein Schichttyp je LOGA-Code mit LOGA-Farbe; vorhandene Typen werden wiederverwendet.
  - Ein Tageseintrag je Tag, weitere Dienste am selben Tag als Zusatzdienste.
  - Abgleich nur der eigenen Einträge (Notiz `pep-scraper`); manuelle Einträge an Tagen ohne LOGA-Eintrag
    bleiben unangetastet. Mehrfaches Ausführen ändert nichts, solange LOGA gleich bleibt.
  - Selbst angelegte Schichttypen werden in `.pep-scraper-state.json` verfolgt (an die Yuvomi-Adresse
    gebunden, mit Fingerabdruck) und aufgeräumt, sobald LOGA sie nicht mehr nutzt.
  - `--dry-run` zeigt Änderungen, ohne zu schreiben.
- **Lesbare Namen:** `schichten.toml` ordnet LOGA-Codes und Abwesenheitstitel Namen und Icons zu
  (Vorlage `schichten.example.toml`); ohne Eintrag gilt die Faustregel F/S/N = Früh-/Spät-/Nachtdienst.
  Eigene Yuvomi-Schichttypen werden bei Namensänderung umbenannt.
- **Abwesenheiten** (`YUVOMI_ABSENCES`): `neutral` zeigt nur bekannte harmlose oder in `schichten.toml`
  freigegebene Titel, Gesundheitsgründe immer als „Abwesend“; dazu `hidden`, `detail` und `skip`.
- **Fehlerbehandlung mit Exit-Codes:** 1 Konfiguration, 2 Anmeldung, 3 Abruf/Wartung, 4 Format,
  5 Yuvomi, 6 Kennwort abgelaufen. Falsches Kennwort und LOGA-Wartung werden sofort erkannt.
- Deutsche Ausgaben, Fehlermeldungen, `--help` und Dokumentation.
- GitHub-Actions-CI: black, isort, ruff, mypy, bandit und Tests (inkl. Browser-Tests gegen ein lokales
  Fake-LOGA); Actions auf Commit-SHAs gepinnt.

### Sicherheit
- Kennwort und API-Token nie in Logs, `repr` oder Fehlermeldungen; URLs mit eingebetteten Zugangsdaten
  werden abgelehnt; nur `https://` (außer localhost).
- Yuvomi-Abgleich berücksichtigt nur Einträge des konfigurierten Mitglieds; gelöscht wird nur, was das Tool
  selbst angelegt hat.
- `PEP_BASE_URL` ist Pflicht, das Repo enthält keine arbeitgeberspezifische Adresse mehr.

[Unreleased]: https://github.com/wbonis/pep-scraper/compare/c50e33d...HEAD
[0.1.0]: https://github.com/wbonis/pep-scraper/commits/c50e33d
