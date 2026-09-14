# Design Notes

Answers to the architecture questions raised while planning, with the reasoning
recorded so the decisions don't have to be re-litigated later.

## Is CSV a second database?

No. The database stays the single source of truth; CSV and JSON are interchange
formats. A CSV "database" loses types, relationships and history, and would have to
be re-validated on every read.

```
                MedFlow data
                     │
                 DATABASE          ← source of truth
          ┌──────────┼──────────┐
         CSV        JSON      Backup
       export     export    snapshot
```

Backups are real database snapshots, taken with SQLite's online backup API so the
file is consistent even while the app is running. Export directories are configurable,
never hardcoded.

## Are we using FastAPI, and does Tkinter prevent localhost or web?

FastAPI is planned for the backend phase — not in this release — and **CustomTkinter
does not prevent any of it**.

- **localhost works.** FastAPI on `127.0.0.1:8000` is just another local process. The
  GUI stays a desktop app; it simply calls `http://localhost:8000` instead of SQLite.
- **Desktop and web can coexist.** They become two clients of one backend. The desktop
  app is not replaced by the web app; both talk to the same API.
- **Codespaces works for the backend, not the GUI.** You can run `uvicorn` in a
  Codespace and forward the port. CustomTkinter needs a graphical display, so the
  desktop client belongs on your machine talking to a remote API. Designing around
  X11 forwarding would be a mistake.

The layered design means adding the API layer later touches `repositories/` only.

## Docker

Docker belongs around the **backend**, not the desktop app:

```
docker compose up
├── medflow-api     FastAPI
├── medflow-db      PostgreSQL
└── medflow-web     web client
```

Dockerising CustomTkinter would mean shipping a windowed app inside a container for no
benefit. The desktop app ships as a PyInstaller executable with its own local SQLite;
the backend stack ships as containers. Different distribution, same repository.

## Supabase

A good target for the **hosted database**, with one architectural condition: Supabase
provides PostgreSQL, not MedFlow's application boundary.

```
desktop / web → FastAPI → PostgreSQL (Supabase)
```

not

```
desktop → Supabase          ← client would hold credentials and trust its own rules
```

Keeping FastAPI in front means the client never holds database credentials,
authorisation is enforced server-side, and the database stays swappable. The
repository interface keeps MedFlow from being welded to Supabase specifically.

## The client must not touch the database

Correct, and it should be stated as a rule rather than a preference. In network mode
the client knows an API endpoint, a contract and a token — never a host, a username,
a password or a schema.

Worth being precise about one thing: **an API does not by itself prevent SQL
injection.** The protections are parameterised queries, server-side validation,
server-side authorisation and secrets kept off the client. The API boundary is what
makes those enforceable in one place instead of everywhere.

## Sync, versioning and conflicts

The Git analogy is the right instinct, and the right implementation is *not* literal
Git. Two ideas are being conflated:

- **Version history** — every record carries `record_version`, `updated_at`,
  `updated_by`. Cheap, and it already exists in schema v1.
- **Change-based reconciliation** — sync operates on *changes*, not on whole patients.

That distinction is what makes conflicts rare. If device A edits a diagnosis while
device B adds an allergy, those are independent changes and merge cleanly. Treating
the patient as one big object would flag a conflict where none exists.

**Last-write-wins is not acceptable here.** Two clinicians recording different
allergies is exactly the case where "whoever saved last" destroys information. Where
the same field genuinely diverged, MedFlow must surface:

```
Conflict — patient MF-000123, field: medication
  local  (Dr A, 10:42): Amoxicillin
  remote (Dr B, 10:47): Ciprofloxacin
  [keep local] [keep remote] [compare] [resolve manually]
```

Not implemented in this release. What this release provides is the prerequisite:
records are already versioned, every change already emits an event, and records are
already decomposed into related tables rather than one flat row.

## Scoped databases: device → department → branch → global

Model these as **logical scopes in one database**, not as a chain of physical
databases:

```sql
organizations / branches / departments / users / patients / records / access_policy
```

One PostgreSQL database, many scopes, with access decided by relationships. Physically
splitting into per-department databases makes cross-department history — the thing that
prevents a prescribing error — significantly harder, and it multiplies backups,
migrations and consistency problems.

A private hospital LAN still works: workstations talk HTTPS to an API on the local
server, and the database is never exposed directly to them.

### Server vs backend

- **Backend** — the application logic: FastAPI, auth, services, validation, audit.
- **Server** — the machine or environment running it: a hospital box, a VM, a
  container host, a managed cloud runtime.

The backend is software; the server is where it runs.

## Departments, roles and shifts must be data, not code

`Radiology`, `Hepatology`, `Orthopedics` are **rows an administrator creates**, not
constants. A hospital that renames a department, merges two, or adds one must not need
a new build. The same applies to roles, permissions and shift definitions.

Cross-department visibility is the payoff: radiology's finding reaches orthopedics,
and pharmacy can see allergies recorded elsewhere. "Everyone sees everything" is not
the goal — *controlled* sharing, by policy, with every access auditable.

## External hospital record exchange

A separate subsystem, not a database connection between institutions:

```
export → structured package → encryption/signing → transfer
      → validation → patient matching → human review → accept → audit
```

**Patient matching is the hard part, and the dangerous one.** Two hospitals each
holding a "John Doe, DOB 12/04/1985" is not proof of one person. An incoming record is
a *candidate* that a human confirms; it is never auto-merged. Real deployments would
target established healthcare interoperability standards rather than a bespoke format —
this project builds the engineering shape of that workflow.

## Automation and patient delivery

Worth building, but as a generic rules engine, never a hardcoded "email records on
Friday":

```
trigger → conditions → actions → delivery → retry → audit
```

Two caveats recorded deliberately:

1. Automated transmission of medical information is a **high-risk feature**, not a
   cron job. Consent, recipient verification, authorisation, encryption, retention and
   an audit trail are prerequisites, not enhancements.
2. For MedFlow as a portfolio project, the deliverable is the **architecture and a
   simulated delivery workflow** — not a claim of production-certified clinical
   infrastructure, and not something to deploy against real patient data.

## Why the local→network move is cheap later

`PatientService` depends on `PatientRepository`, an interface. Adding network mode
means writing `ApiPatientRepository`. The services, views and dialogs are unchanged —
they never knew SQLite was there. That is the return on this refactor.

## Two invariants that look like omissions

Both of these read as missing code. They are deliberate, and someone will eventually
try to "fix" them, so the reasoning is recorded here.

**`PatientRepository.insert()` does not write diagnoses.** A patient arrives with a
diagnosis attached, and it is natural to expect the repository to persist the whole
object. It does not: diagnoses are written only through `add_diagnosis()`, so there is
exactly one code path that creates a diagnosis row, and every such row is a deliberate
act with its own timeline entry and audit record. If `insert()` also wrote them, there
would be two paths — and the one nobody was looking at would be the one that skipped
the history.

**Soft delete is not a shortcut around `DELETE`.** Three things depend on it:

- `sequences` — the counter behind patient numbering. Allocating from
  `MAX(patient_number) + 1` would let a new patient inherit a deleted patient's
  number, which is unacceptable in a clinical record. A monotonic counter cannot.
- `patient_events` and `diagnoses` — the record's clinical history. Deleting them
  because the patient was removed would destroy the audit trail of care that was
  actually given.
- Recoverability — `restore()` returns a soft-deleted patient intact, which a hard
  delete cannot.

Note the deliberate asymmetry: `patient_events` and `diagnoses` carry
`ON DELETE CASCADE`, while `audit_log` has **no** foreign key at all. The audit trail
must outlive the record it describes — that is the point of an audit trail.
