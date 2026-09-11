# MedFlow Roadmap

Status legend: **done** · **now** (this release) · next · later

## Foundation — complete

| | Item |
|---|---|
| done | Desktop UI (CustomTkinter) |
| done | SQLite persistence |
| done | Create / Read / Delete |
| done | Search |
| done | Automatic patient IDs |
| done | Theme switching |

## Foundation — finishing in this release

| | Item |
|---|---|
| now | Update (completes CRUD) |
| now | Modular architecture: services + repositories |
| now | Domain models, decoupled from storage |
| now | Strong validation at the service layer |
| now | Structured exceptions instead of bare `except` |
| now | Application logging, separate from the audit trail |
| now | Relational schema with migrations |
| now | Patient change history |
| now | Application-wide audit log |
| now | Sorting and filtering |
| now | Patient record sections (overview / vitals / diagnoses / activity) |
| now | Backup and restore |
| now | CSV and JSON export |
| now | CSV import with dry-run validation |
| now | Dashboard metrics |
| now | Settings persisted to disk |
| now | Automated test suite |
| now | Configuration system, nothing hardcoded |

## Distribution — next

| | Item |
|---|---|
| next | PyInstaller single-file build |
| next | Windows installer and application icon |
| next | Semantic versioning and tagged releases |
| next | GitHub Actions: test, lint, build, attach `.exe` to a release |

## Backend — next

| | Item |
|---|---|
| next | FastAPI service exposing the same operations as the repositories |
| next | Pydantic request/response schemas |
| next | `ApiPatientRepository` — network mode with no UI changes |
| next | Authentication and server-side authorisation |
| next | PostgreSQL persistence |
| next | API integration tests |

## Cloud and multi-user — later

| | Item |
|---|---|
| later | Supabase (managed PostgreSQL) as the hosted database |
| later | Organisations, branches, departments, roles and permissions |
| later | User accounts, shift assignments, per-user audit attribution |
| later | Cross-department record visibility with access policy |
| later | Deployment with HTTPS |

## Synchronisation — later

| | Item |
|---|---|
| later | Change tracking and record versioning across devices |
| later | Sync engine: push local changes, pull remote changes |
| later | Conflict detection per record, not per patient |
| later | Conflict resolution: auto-merge independent fields, human review otherwise |
| later | Sync status surfaced in the UI |

## Interoperability — later

| | Item |
|---|---|
| later | Structured record export package for another institution |
| later | Import validation and review workflow |
| later | Patient matching (an incoming record is a *candidate*, never an automatic merge) |
| later | Transfer audit trail |

## Automation — later

| | Item |
|---|---|
| later | Scheduler and configurable automation rules |
| later | Consent and authorisation checks before any delivery |
| later | Patient-facing delivery with retry and delivery status |

## Web client — later

| | Item |
|---|---|
| later | Browser client sharing the FastAPI backend with the desktop app |

## Engineering practice — ongoing

| | Item |
|---|---|
| now | Test suite (unit + integration) |
| next | Linting and type checking in CI |
| next | Docker Compose for the backend and database |
| later | Multi-platform builds and automated releases |

## Guiding constraints

1. **Nothing hardcoded.** Departments, roles, ID prefixes, paths, thresholds and
   validation bounds are configuration, never literals in the source.
2. **Clinical safety over convenience.** No last-write-wins on medical records. No
   silent merging of two patients' data.
3. **The client is never trusted.** In network mode the desktop app holds an API
   endpoint and a token, never database credentials.
4. **Additive change.** Each phase should be addable without rewriting what is
   already working.
