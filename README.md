# MedFlow

**A local-first clinic management platform — desktop app, self-hosted web workspace, and an open JSON API, all from one Python codebase and one SQLite database you own.**

MedFlow is built for independent practices, clinics, and small hospitals that want real medical-records software without sending patient data to someone else's cloud, without subscriptions per seat, and without an IT department. It runs entirely on your machine or your own server, works offline by default, and grows with you: start as a single-workstation desktop app, then switch on the web/API server and device sync when you add staff or branches — without migrating anything.

If you know the category names: MedFlow is an **offline-first, self-hosted EMR (electronic medical record) with practice-management features** — patient directory, structured clinical charting, appointments, reporting, exports, audit trail, backups, and inter-facility record exchange. Think "the open, local-first alternative to clinic SaaS."

---

## Why this exists — and what we learned from the best

MedFlow's design is a distillation of a research pass over the software that actually thrives in this space, and the reasons clinicians keep using it:

| Product | What it is | Why people stay | What MedFlow took |
|---|---|---|---|
| **OpenEMR** | The most widely adopted open-source clinic suite | Everything in one system — records, scheduling, reporting — at zero license cost | The all-in-one scope: charting + scheduling + reports + exports in one install |
| **OpenMRS / Bahmni** | Global-health EMR platforms built for low-resource settings | Offline-first reliability where connectivity is not guaranteed | The local-first architecture: the app is fully usable with no internet, sync is optional |
| **GNU Health** | Health + hospital information system with strong data-ownership ethics | Data belongs to the facility, not the vendor | Plain-file SQLite storage, portable backups, no vendor cloud, open export formats |
| **Odoo / Frappe Healthcare** | Modern modular ERP-style healthcare apps | Clean, calm, contemporary UI that feels like modern SaaS | The visual language: card-based dashboard, one accent color, generous spacing, no widget clutter |
| **Jane / Carepatron / Praxis EMR** | Commercial tools clinicians consistently rate highest for usability | Speed to the task: search-first navigation, few clicks, chart-at-a-glance, low cognitive load | The UX patterns: instant search, timeline-oriented patient chart, inline entry rows per chart section, keyboard-friendly forms |

The pattern across all of them is clear — **adoption is won by speed, calm interfaces, and trust**:

1. **Speed to the task.** Search-first navigation; any patient in under a second; chart sections have inline "add" rows so documenting a visit is one screen, not five dialogs.
2. **Calm, clinical visual identity.** One deep-teal accent, clear hierarchy, readable tables. Software that feels quiet reduces the documentation fatigue clinicians cite as the top EHR complaint.
3. **Trust through ownership and transparency.** The database is a file you can hold. Every action is in the audit trail. Backups are plain SQLite you can email to yourself.
4. **Offline resilience.** A power cut or dead router must never stop a clinic from working. MedFlow's desktop face never needs a network.
5. **Exit ramps, not lock-in.** CSV/JSON exports, printable charts, portable transfer bundles. Your data leaves as easily as it arrived.

MedFlow implements all five as architecture, not slogans.

---

## What MedFlow does today

### A real front door

The web server ships a complete public site — **landing page, features, security, and a how-to guide** — with top navigation and a hideable sidebar menu, in the same calm clinical design. Login and signup pages cross-link both ways; protected areas redirect to sign-in.

- **Self-service signup** — the first account on a fresh install becomes the administrator; later signups start as viewers pending promotion. (Disable open signup per deployment in `config.json`.)
- **Sign in with Google** — optional; set `MEDFLOW_GOOGLE_CLIENT_ID` in the environment. ID tokens are verified against Google's published keys (pure-Python RS256, no extra dependencies) with audience, issuer, expiry, and verified-email checks. Works in the web app and the desktop app.
- **Temporary visitors** — administrators mint scoped, time-limited accounts: choose the patients, set the window (1 hour – 30 days), share the generated credentials. Guests see only those records, can write nothing, are cut off the moment the window closes, and can be revoked instantly. Manage them in the web workspace's **Access** panel or desktop **Settings → Temporary access**.

### Two faces, one brain

```
┌────────────────────────┐        ┌────────────────────────┐
│  Desktop (CustomTkinter)│        │  Web + API (FastAPI)    │
│  offline workstation    │        │  self-hosted, multi-user│
└───────────┬────────────┘        └───────────┬────────────┘
            │     both call the same services  │
┌───────────▼──────────────────────────────────▼────────────┐
│          Service layer (validation · permissions · audit)  │
┌───────────────────────────────────────────────────────────┐
│          Storage layer (versioned SQLite · migrations)     │
└───────────────────────────────────────────────────────────┘
```

One command each: `python main.py` for the desktop, `python main.py --server` for the web face. Both read the same `config.json`, write the same database, and enforce the same permission model.

### Patient management
- Patient directory with **instant search** across patient number, name, phone, and diagnosis (as-you-type in both faces)
- Stable, human-readable patient numbers (`MF-000042`) that are **never reused**, even after deletion
- Full demographics, with validation defense-in-depth (age vs. date-of-birth cross-checks, BP format and range guards, phone/email/URL formats — the UI, the service layer, and the API all validate)
- **Soft delete + restore** with a recycle bin in Settings — deletion is recoverable, and the audit trail records who deleted what
- Soft **duplicate-check hints** on email at registration

### Structured clinical charting
The chart is sectioned the way clinicians think, each with inline add-rows:
- **Vitals** — BP, heart rate, temperature, respiratory rate, SpO₂, with physiologic range validation and timestamps
- **Diagnoses** — free text + ICD-style code, status flow (active / chronic / suspected / resolved) with resolution dates
- **Medications** — dose, route, frequency; active → discontinued lifecycle with end dates
- **Allergies** — substance, reaction, severity (mild/moderate/severe/unknown)
- **Lab results** — panel + analyte + value + reference range; **critical flags raise an audit event** and light up the dashboard
- **Clinical notes** — progress, radiology, pharmacy, discharge categories
- **Clinical timeline** — every one of those actions appends to a per-patient narrative timeline: the story of the patient at a glance

### Appointments
- Schedule with provider, reason, and duration; today/upcoming scopes
- **Status flow** — scheduled → checked in → in progress → completed, plus cancellation and no-show, each transition written to the patient timeline
- Dashboard integration: today's count and the next visits

### Roles, security, and the audit trail
- **Argon2-hashed passwords** (bcrypt readable for migration) — never plaintext, never reversible
- **Seven roles** — administrator, physician, nurse, technician, reception, viewer, and temporary — mapped over a fine-grained permission vocabulary (`patients.create`, `records.edit`, `appointments.manage`, `export.data`, `users.manage`, …)
- Permissions shape **both faces live**: desktop menus, web buttons, and API routes all check the same vocabulary, so demoting a user instantly shrinks the app they see
- **Full audit trail** — logins, every create/update/delete, exports, transfers, syncs — with actor, device, and timestamp; filterable in the Activity view, exportable as a dataset
- API bearer tokens are **HMAC-signed with expiry**, with the secret stored per-installation; tokens die in 12 hours, deactivation kills access instantly

### Reports and data portability
- **Dashboard aggregates** — patients, new-this-week, active diagnoses, appointments today, critical labs, database size
- **Trends** — top diagnoses, provider workload, registration activity
- **Exports** — every dataset (patients, appointments, diagnoses, medications, audit) to **CSV or JSON**, plus a **printable HTML patient chart** that opens straight into the browser's print dialog
- **Backups** — one-click consistent SQLite snapshots (safe even while the app is running), integrity verification, restore, retention pruning; automation rules can take them on schedule
- **Bulk import** — register patients from any CSV with a header row via the CLI, with per-row validation reporting

### Multi-facility: sync and exchange
- **Network mode** — a desktop workstation can point at a MedFlow server (`Settings → Connect to server`) so multiple machines share one database
- **Sync engine** — offline-first change tracking with per-field conflict detection; rows carry `version`, `updated_at`, `device_id`; push/pull is dry-run safe when no server is configured
- **Inter-facility exchange** — export any patient as a self-contained, **SHA-256 checksummed transfer bundle** (`.medflow.json`) and import it at another facility as a new record or a supervised merge (conflicting fields reported, never silently overwritten). No shared server, no cloud — a USB stick or email attachment moves a complete chart.

### Automation
- Declarative **"when fact X crosses threshold, do Y"** rules — e.g. *when total patients ≥ 500 → create a backup*, *when critical labs > 0 → log an alert* — built in Settings, run on a schedule or on demand, with per-rule run history

---

## Quick start

### Desktop app (the default face)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

First run creates `data/medflow.db` and the config automatically. Create your administrator from the CLI first (see below), then sign in at the login window.

### Web + API server

```bash
python main.py --server --port 8000
```

- Web workspace: `http://127.0.0.1:8000/`
- Interactive API docs: `http://127.0.0.1:8000/docs`

### CLI — setup, ops, and automation

```bash
# one-time: create the database and an administrator
python -m app.cli init --admin-user admin --admin-password "s3cret-please-change"

# dashboard numbers in the terminal
python -m app.cli stats

# snapshots
python -m app.cli backup
python -m app.cli restore data/backups/medflow_XXXX.db

# exports and bulk import
python -m app.cli export patients --fmt csv --out roster.csv
python -m app.cli import-patients new_patients.csv
```

### Tests

```bash
python -m pytest tests/ -q
```

### Package for distribution (Phase 7)

```bash
pip install pyinstaller
pyinstaller MedFlow.spec
# → dist/MedFlow (Windows: dist/MedFlow.exe)
```

The executable bundles the UI and web assets; the database is created beside it at runtime, so patient data stays with the installation.

---

## The API

The web face is a full JSON API (OpenAPI docs at `/docs`). Highlights:

```
POST   /api/auth/login                     → bearer token
POST   /api/auth/signup                    → self-service registration
POST   /api/auth/google                    → Google sign-in (optional)
GET    /api/auth/config                    → public login-page configuration
GET    /api/patients?q=…                   → search (auth)
POST   /api/patients                       → register (patients.create)
PATCH  /api/patients/{id}                  → true PATCH semantics
DELETE /api/patients/{id}                  → soft delete (patients.delete)
GET    /api/patients/{id}/chart            → every chart section at once
POST   /api/patients/{id}/vitals|diagnoses|medications|allergies|lab-results|notes
GET    /api/appointments?scope=today       → schedule
PATCH  /api/appointments/{id}/status       → lifecycle transitions
GET    /api/temp-users                     → list guest accesses (users.manage)
POST   /api/temp-users                     → mint a scoped, timed visitor
DELETE /api/temp-users/{id}                → revoke immediately
GET    /api/reports/dashboard              → aggregates
GET    /api/export/{dataset}.csv|.json     → downloads
GET    /api/patients/{id}/chart.html       → printable chart
POST   /api/sync/pull  ·  /api/sync/push   → device sync
POST   /api/exchange/{id}/export           → transfer bundle
GET    /api/health                         → public status
```

Public site routes: `/` (landing), `/features`, `/security`, `/guide`, `/login`, `/signup`, and `/app` (the signed-in workspace).

Domain errors arrive as structured JSON with per-field messages (`{"error": {"message": …, "fields": {…}}}`), so any client — the built-in web app, the desktop, or a third-party integration — can render them properly.

---

## Architecture

```
app/
├── models/        domain models (patient, 6 chart types, org, audit)
├── storage/       the ONLY code that touches SQL
│   ├── schema.py        versioned schema, 14 tables
│   ├── migrations.py    user_version-keyed migration runner
│   ├── engine.py        per-thread connections, WAL, durable writes
│   └── repositories.py  model-typed queries for every entity
├── services/      business logic — validation, permissions, audit
│   ├── patients.py  records.py  org.py  security.py
│   ├── reports.py   export.py  backup.py
│   ├── sync.py      exchange.py  automation.py
├── server/        FastAPI app + token auth + built-in web client
├── ui/            CustomTkinter desktop (views, components, theme)
├── cli.py         command-line interface
└── controller.py  desktop session wiring
```

Design rules that keep it honest:

- **One business logic.** Both UIs bind to the same services; there is no second implementation to drift.
- **SQL lives in one place.** Services never see SQL; repositories return domain models; the schema is versioned and migrated, so upgrades are ordered and safe.
- **Concurrency-proof storage.** Per-thread connections, WAL journaling, foreign keys on, serialized durable writes — the desktop and the server can share one database safely.
- **Typed errors end to end.** `ValidationError` carries field maps; the desktop forms and the API responses both render them.

---

## Where the name sits

*LMS* is learning, *SaaS* is a delivery model — MedFlow is neither on its own. It is a **local-first EMR / clinic-management platform**: vertical application software for a specific industry (healthcare), delivered as an installable product with an optional self-hosted server. If a one-liner helps: *"EMR software that lives on your machine."*

---

## Roadmap

Everything on the current plan is **implemented and shipping in this repo** — nothing is parked. Natural next steps when the clinic grows into them (each is an extension, not a rewrite, thanks to the layered architecture):

- OIDC/LDAP login against a hospital directory
- FHIR-style JSON payloads for the exchange bundles
- PostgreSQL adapter behind the same repository interface for multi-site installs
- Desktop auto-update channel and code-signed installers
- Optional end-to-end encryption for transfer bundles (recipient keyfiles)

## License & data ownership

MedFlow stores data in open formats (SQLite, CSV, JSON, HTML) and ships no telemetry, no license servers, and no third-party calls. Your patients' records never leave machines you control.
