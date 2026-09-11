# MedFlow Architecture

## The one rule

> The user interface never talks to storage. Services never know how storage works.

Everything below exists to enforce that sentence.

## Layers

```
        Desktop UI (CustomTkinter)
                  │
                  │  calls methods, passes/reads domain objects
                  ▼
             Services              business rules, validation, orchestration
                  │
                  │  depends on an abstract interface only
                  ▼
          Repositories             PatientRepository (ABC)  ← the seam
              ╱       ╲
             ╱         ╲
   SQLiteRepository   ApiRepository (future)
        │                   │
     medflow.db        FastAPI → PostgreSQL/Supabase
```

### `app/domain`
Plain data. No database imports, no Tk imports, no I/O. `Patient`, `Diagnosis`,
`PatientEvent`, `AuditEntry`, `DashboardSummary` and the enums. Because these are
storage-agnostic, the same objects flow through a local SQLite call and a future
HTTP call unchanged.

### `app/repositories`
Abstract interfaces (`PatientRepository`, `HistoryRepository`, `AuditRepository`)
plus the SQLite implementations under `repositories/sqlite/`. **This is the file
that changes when MedFlow gains network mode** — and nothing above it changes.

### `app/services`
Where the rules live. `PatientService.create_patient()` validates input, allocates a
patient number, writes the record, records a history event and writes an audit entry
as one logical operation. A button callback calls this method; it never sees SQL.

### `app/core`
Cross-cutting infrastructure: the exception hierarchy, structured logging,
validators and an injectable clock (so tests can assert on timestamps).

### `app/config`
A single `AppSettings` object, persisted as JSON. Nothing is hardcoded — database
location, ID prefix and padding, backup/export/log directories, appearance mode,
validation bounds and storage mode all come from here.

## Why the repository seam matters

The cost of adding network mode later is one new class:

```python
class ApiPatientRepository(PatientRepository):
    def search(self, query, ...):   # GET /patients?q=...
    def create(self, patient):      # POST /patients
    ...
```

`PatientService`, every view, and every dialog stay untouched, because they only
ever referred to the interface. That is the entire point of this refactor.

The client must **never** hold database credentials. In network mode the client knows
an API endpoint and a token — not a host, a schema, or a password. Server-side
authorisation is what protects records, never the client.

## The composition root

`app/container.py` is the only place in MedFlow that knows storage is SQLite:

```python
Container.build(settings)   # → settings, clock, database, services
```

Nothing constructs its own dependencies. Each object receives what it needs as
constructor arguments, so the graph can be assembled against a temporary database or
with a frozen clock — which is exactly what the tests do. Swapping the SQLite
repositories for HTTP clients is an edit to this one file.

Views receive the container, never a repository. That is the rule the UI tests check
mechanically: no module under `app/ui/` may import `sqlite3` or reach into
`app.repositories`.

## Time is injected, not read

Timestamps are obtained from a `Clock` rather than by calling `datetime.now()` at the
point of use:

```python
class Clock(Protocol):
    def now(self) -> datetime: ...      # aware UTC datetime
    def timestamp(self) -> str: ...     # "2026-03-04 10:30:00", what SQLite writes
    def today(self) -> str: ...         # "2026-03-04"
```

`SystemClock` is what runs; `FixedClock` is pinned to a known moment and can be
advanced (`clock.advance(days=1)`), so a test can assert on a stored `created_at` or
prove that a second edit moved `updated_at`.

Three methods rather than one because timestamps are stored as strings. Formatting
them at each call site would mean repeating the same conversion in a dozen places,
and getting it wrong in one of them.

The format is deliberate: `YYYY-MM-DD HH:MM:SS` in UTC is exactly what SQLite's
`CURRENT_TIMESTAMP` produces, so rows written by the pre-refactor application sort
correctly alongside new ones rather than straddling a format boundary.

## Storage: schema v1

The original app stored everything in one flat `patients` table
(`patient_id, name, age, bp, hr, history, diag`). That cannot express a patient with
a history of diagnoses, and it cannot express who changed what.

| table | holds |
|---|---|
| `patients` | identity and demographics, plus `record_version`, `updated_at`, soft-delete `deleted_at` |
| `patient_records` | the current clinical snapshot — blood pressure, heart rate, weight, height, medical history, notes |
| `diagnoses` | one row per diagnosis, with status and notes (many per patient, not one overwritten field) |
| `patient_events` | what happened to this patient, in order — the per-record timeline |
| `audit_log` | what happened in the application — who did what, across all entities |
| `sequences` | monotonic counters backing patient numbering |
| `schema_migrations` | ledger of applied migrations |

### Two distinctions worth keeping straight

**Clinical history vs audit log.** `patient_events` answers *"what is this patient's
story?"* — shown to a clinician. `audit_log` answers *"who touched this record, and
when?"* — a compliance and traceability record. They are related but not the same,
and conflating them makes both worse.

**Deleted vs gone.** Deleting a patient sets `deleted_at` (soft delete). Combined
with the `sequences` table, this is what guarantees the original app's promise that
patient numbers are never reused after a deletion. A hard `DELETE` would let a new
patient inherit a dead patient's number — unacceptable in a clinical record.

### Patient numbering

`MF-000001` is `{prefix}-{padded sequence}`, and **both the prefix and the padding
are configurable**. The number is allocated from `sequences`, never from
`MAX(number) + 1`, so soft-deleted records can't cause a collision.

## Migrations

Forward-only, idempotent, tracked with SQLite's `user_version`. `MigrationRunner`
asserts the database is not newer than the code, then applies each pending step in a
transaction.

`migrations.legacy` (module `app/repositories/sqlite/legacy.py`) detects the
pre-refactor flat `patients` table and converts it:

| legacy | becomes |
|---|---|
| `patient_id = "Patient 001"` | `patient_number = "MF-000001"` (ordinal preserved) |
| `name = "John Doe"` | `first_name = "John"`, `last_name = "Doe"` |
| `age = "32"` | `age_years = "32"` |
| `bp`, `hr`, `history` | one `patient_records` row |
| `diag` | one active `diagnoses` row |
| — | a `MIGRATED` patient event and an audit entry, per patient |

`age_years` stays alongside nullable `date_of_birth` deliberately. The old app
captured age as free text (`"32"`, `"--"`); recording that honestly is better than
silently inventing a date of birth that a clinician might later trust.

The whole conversion runs in one transaction: if any record fails, nothing is
migrated and the original data is untouched.

## Demo data

`app/services/seed.py` creates the three sample patients on first run, and only when
the register is completely empty. It seeds **through `PatientService`**, not by
inserting rows — so demo records get their numbers from the same counter, carry the
same timeline entries and appear in the audit trail as any other record. A seeded
patient is indistinguishable from a typed one, which means the demo data exercises
the real code path instead of a parallel one that can quietly rot.

The check is `count(include_deleted=True) == 0`. A register emptied by deletion is
not a new installation, so deleting every patient does not bring the demo data back.

## Backup, export and import

The **database is the source of truth**. CSV and JSON are interchange formats, not a
second store — a CSV "database" would lose types, relationships and history.

- **Backup** — a consistent snapshot (`sqlite3` backup API) into `backups/`, timestamped.
- **Export** — patients to CSV or JSON, for hand-off and reporting.
- **Import** — CSV through validation, then a **dry-run preview** reporting how many
  rows are valid and exactly which are not, before anything is written.

Import never blindly inserts. A rejected row is reported with its line number and
reason, and the operator decides.

## Configuration

`AppSettings` is a dataclass persisted as JSON, loaded from a path resolved in this
order:

1. an explicit path passed by the caller
2. `MEDFLOW_CONFIG` environment variable
3. `config.json` beside the application

Every field has a default, so MedFlow runs with no config file at all — which is what
makes the packaged `.exe` double-click-and-go.

## Non-goals (for this release)

No network code, no ORM, no web client, no sync engine. Those are designed for — the
seam exists at `repositories/` — but deliberately not built yet.
