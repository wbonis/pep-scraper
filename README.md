# pep-scraper

Exports your own PEP duty roster from P&I LOGA3 (`harzklinikum.pi-asp.de`) to an ICS file.

Logs in with headless Chromium (Playwright) and captures the JSON the dashboard loads from
`/loga3/private/api/dashboard/pep/loadShiftsDashboard` (90 days ahead). No HTML scraping,
xsrf handling stays with the app.

## Setup

```sh
uv sync
uv run playwright install chromium
cp .env.example .env && chmod 600 .env   # fill PEP_USERNAME / PEP_PASSWORD
```

## Run

```sh
uv run pep-scraper            # writes ./dienstplan.ics
uv run pep-scraper -v --env-file /path/to/.env
```

Exit codes: `0` ok, `1` config, `2` login (wrong credentials, captcha, 2FA), `3` fetch, `4` unexpected JSON.
On any error the previous ICS file is kept.

Mapping:
- Shifts become timed events (`N003 21:45-06:15`). Night shifts end the next day.
- `00:00-00:00` entries (e.g. `FREI`) and absences (e.g. `Urlaub`, `Fortbildung`) become all-day events.
- UIDs are stable per day and shift, so calendar apps update instead of duplicating.

## Daily run (cron)

```cron
15 6 * * * cd /path/to/pi-asp && /opt/homebrew/bin/uv run pep-scraper >> ~/Library/Logs/pep-scraper.log 2>&1
```

## Dev

```sh
uv run pytest                 # incl. browser tests against a local fake LOGA
uv run pytest -m "not browser"
uv run ruff check src tests && uv run mypy src tests && uv run bandit -r src
```
