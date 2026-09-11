# MedFlow

A local desktop patient-management application for a clinic: Python, CustomTkinter and
SQLite. No API keys, no `.env`, no internet connection required.

Version 2 rebuilt the application around a layered architecture so that storage can
later move behind an API without the interface being rewritten. The v1 codebase is
preserved as the [`v1.0-local-db`](https://github.com/laxjovial/MedFlow/releases) release.

## Features

**Patients** — a full record, not a row in a table.

- Create, view, edit and delete patients
- Search across name, patient number and diagnosis
- Sort by patient number, name, or when the record was created or last changed
- Diagnoses as a history — one row per diagnosis, each with a status, rather than a
  single field that gets overwritten
- A per-patient timeline: what happened to *this* record, and when
- Soft delete. A deleted record is hidden but recoverable, and its number is never
  reused

**Dashboard** — totals, today's activity, recent changes and the diagnosis mix.

**Activity** — an application-wide audit log: who created, changed, deleted, exported,
imported or backed up what. Separate from the patient timeline, which answers a
different question (see [ARCHITECTURE.md](docs/ARCHITECTURE.md)).

**Settings** — appearance, and data management: backups, CSV/JSON export, and import.

**Data**

- Backups taken through SQLite's own online backup API, safe while the app is running
- Export to CSV or JSON
- Import that validates every row, shows a dry-run preview, and skips bad rows with a
  reason rather than failing the whole file

**Interface** — light/dark/system appearance, keyboard shortcuts (`Ctrl-N` new
patient, `Ctrl-F` search, `Ctrl-R` refresh, `Esc` clear).

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The database is created automatically on first run. So are three demo patients — set
`"seed_demo_data": false` in `config.json` before the first launch if you would rather
start with an empty register.

## Configuration

Nothing is hardcoded. Every path, the patient-number format, the validation bounds and
the appearance defaults are read from `config.json` beside the application. It is
optional: MedFlow runs on built-in defaults when the file is absent.

```json
{
  "database": { "directory": "data", "filename": "medflow.db", "seed_demo_data": true },
  "patient_ids": { "prefix": "MF", "padding": 6 },
  "directories": { "backups": "backups", "exports": "exports", "logs": "logs" },
  "validation": { "min_age": 0, "max_age": 130 },
  "appearance": { "mode": "System", "color_theme": "blue" },
  "storage": { "mode": "local" }
}
```

Patient numbers are `{prefix}-{sequence padded to padding}`, so `MF` + `6` gives
`MF-000001`. Unknown keys are rejected rather than ignored — a typo in a settings file
should be reported, not silently obeyed as a default.

Point MedFlow at a different config file with `MEDFLOW_CONFIG=/path/to/config.json`.

## Development

```bash
pip install -r requirements-dev.txt
pytest                                    # full suite
pytest tests/unit                         # fast, no database
pytest -q --tb=short -k "not slow"
```

```
app/
  main.py            bootstrap: settings → logging → migrate → container → UI
  container.py       the composition root — the only place that knows storage is SQLite
  config/            AppSettings (JSON-backed), constants
  core/              exceptions, logging, validators, clock
  domain/            plain data: patient, diagnosis, events, audit, summary, enums
  repositories/      abstract interfaces + sqlite/ implementations
  services/          validation, change tracking, audit emission, backfill
  ui/                shell, theme, views/, dialogs/, widgets/
docs/                ARCHITECTURE.md, DESIGN_NOTES.md, ROADMAP.md
tests/               unit/, integration/, ui/
```

`main.py` at the repository root is a shim, so `python main.py` keeps working.

### The rule the architecture enforces

```
ui  →  services  →  repositories (ABC)  →  sqlite
                                      ↘  (future) api  →  FastAPI → PostgreSQL
```

The UI never imports `sqlite3` and never writes SQL. Services never know which
repository they hold. That second property is what makes local → network a new class
rather than a rewrite — and it is checked by a test, not just by convention.

## Non-goals in this release

No network code, no ORM, no web client, no sync engine. Those are designed for — the
seam exists at `app/repositories/` — but deliberately not built. See
[docs/ROADMAP.md](docs/ROADMAP.md).

## Package for Windows

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name MedFlow main.py
```

The executable appears at `dist/MedFlow.exe`. It cannot write beside itself on every
platform, so a packaged build passes an explicit base directory to `AppSettings`.

## Patient data

`data/`, `backups/`, `logs/`, `exports/` and `config.json` are git-ignored. Patient
records must never be committed, and exports and backups are as sensitive as the
database itself — treat a CSV you have exported exactly as you would the database.

## License

See [LICENSE](LICENSE) if present; otherwise contact the repository owner.
