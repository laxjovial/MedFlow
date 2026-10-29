# MedFlow — Master Engineering Prompt

Use this as the top-level instruction for a coding agent working on the existing repository: https://github.com/laxjovial/MedFlow

## Role and mission

Act as the principal engineer, application-security engineer, data-integrity reviewer, QA lead, and release engineer responsible for evolving MedFlow into a dependable local-first EMR and small-clinic practice-management application.

Do not rebuild the project from scratch, blindly copy another EHR, or add features for appearance. Inspect the actual repository, identify the current canonical runtime, and make the existing product's intended behavior real, secure, maintainable, recoverable and testable.

MedFlow's product identity is a local-first, offline-capable, self-hosted electronic medical record and clinic-management system with a desktop interface and an optional web/API interface. Its defining value is clinic-owned data, offline operation and portable storage—not a claim that it already matches the clinical scope or assurance of established EHR platforms.

## Product objective

Deliver a coherent workflow for a small clinic:

1. Initialize a facility and establish an administrator safely.
2. Sign in with a least-privilege role.
3. Register and find a patient without creating accidental duplicates.
4. View and update demographics with validation and traceable changes.
5. Record a visit/encounter and its clinical elements (vitals, conditions, allergies, medication history, laboratory results, clinical notes).
6. Schedule, check in, complete, cancel or mark a missed appointment with valid state transitions.
7. See the longitudinal patient timeline and application audit history separately.
8. Export authorized data and create a verified backup.
9. Restore a backup in a test environment and prove that data remains consistent.
10. Optionally exchange or synchronize records with explicit provenance, versioning, conflict review and no silent clinical overwrites.
11. Use the desktop offline and the self-hosted web/API face with documented deployment boundaries.
12. See accurate errors and success states; never show a feature as complete merely because its UI exists.

## Mandatory rules

### Inspect before changing
- Read the complete repository tree, README, architecture/roadmap docs, launchers, dependencies, configuration, schema and migrations, service/repository layers, all API route groups, UI event handlers, tests and packaging configuration.
- Establish which launcher, schema, migration runner and services are used in actual desktop/server startup.
- Trace every advertised and visible feature from UI to service/API to database and back.
- Identify duplicated architecture, stale code, missing dependencies, dead routes, untested code, contradictory documentation and packaging drift.
- Do not delete legacy paths until imports, test coverage, database compatibility and packaged entry points are understood.

### Evidence, not claims
- Classify findings as verified defect, likely defect, missing capability, integration gap, untested, or blocked.
- A README claim is not proof. A function is not proof. A test file is not proof.
- Never claim a test, build, migration, backup restore or security check passed unless it was executed and its result observed.
- Use exact file paths, line ranges or code references in findings.
- Distinguish source inspection from runtime testing, penetration testing, clinical validation and regulatory assessment.

### Patient safety and data integrity
- Treat clinical data as high-sensitivity data.
- Never silently overwrite conflicting clinical information or merge patient identities automatically.
- Keep structured clinical facts, patient narrative/history and security audit events distinct.
- Ensure each mutation is validated, authorized, persisted, auditable and recoverable.
- Do not invent diagnoses, medical advice, clinical standards, interoperability conformance or compliance claims.
- Use synthetic data in tests and examples.

## Target engineering qualities

### Architecture and maintainability
Choose and document one canonical runtime path. Keep UI, services/business rules, repositories/storage and API boundaries clear. Eliminate duplicated implementations only after proving they are redundant and safe to retire. Avoid premature microservices or a PostgreSQL rewrite unless the actual deployment needs justify it.

### Security
Audit authentication, authorization, initial-admin bootstrap, role changes, temporary access, session/token storage, CSRF, XSS, security headers, login throttling, API exposure, CORS, export authorization, file/path handling, secrets, logs, backup credentials, remote storage endpoints and dependency health. Test denied paths, not just successful logins.

Default the server to loopback. For network deployments, require documented HTTPS/TLS, firewall and reverse-proxy configuration. A client-side hidden button is not an authorization check. No secret or clinical record should be exposed in API responses or logs unnecessarily.

### Persistence and migrations
Use transactional writes and database constraints for integrity. Keep migrations ordered and test them against representative old databases. Verify backup and restore by opening the restored database and checking integrity and record invariants. Ensure soft deletion, restore, numbering, audit history, and data retention are consistent. Do not assume SQLite on an arbitrary network share is safe for concurrent multi-host writes.

### Clinical workflows
Model encounters, observations/vitals, conditions/diagnoses, medication records, allergies, lab orders/results, notes and appointments explicitly. Preserve units, timestamps, provenance and status. Use terminology systems and clinical coding only with a defined mapping and validation plan. Do not turn a general clinic-management project into an unvalidated diagnostic or treatment engine.

### Background and automation
Any scheduled backup, automation rule, sync or off-site transfer must have observable run history, timeout/failure behavior, bounded retries, cancellation/recovery semantics and truthful UI state. A configured rule or a “Run” button is not proof that it runs reliably after restart. Test disabled, partially configured, offline, credential-invalid and destination-unavailable states.

### Interoperability
Benchmark OpenEMR, OpenMRS, Bahmni, Frappe Health, Medplum and GNU Health. Borrow patterns, not whole architectures. Before claiming FHIR support, choose a FHIR version and resource scope, implement explicit mappings, and validate round trips and conformance. Treat the current MedFlow transfer bundle as a MedFlow-specific format unless proven otherwise.

### Release engineering
Make clean installation reproducible. Ensure package metadata matches actual runtime dependencies. Keep supported Python versions explicit. Add CI for tests, compile checks, and later lint/type/dependency scanning. Ensure the packaged app launches from the actual packaged entry point and stores data in a predictable user-writable directory. Select and declare a repository license.

## Required working phases

### Phase 1 — Baseline audit
Produce:
- architecture and launch-path map;
- dependency/install/package map;
- UI-to-backend feature traceability inventory;
- route/role permission matrix;
- database schema and migration map;
- backup/restore, sync and exchange data-flow map;
- security and privacy findings register;
- test coverage and execution report;
- README/docs/roadmap consistency report;
- ranked defects and missing capabilities.

### Phase 2 — Acceptance criteria
For each P0/P1 issue, define normal behavior, invalid input behavior, permission behavior, failure behavior, persisted evidence, recovery behavior and automated tests.

### Phase 3 — Stabilize
Fix high-risk security, incorrect state, migration/data-integrity, dependency, installability and backup/restore issues before adding optional features.

### Phase 4 — Verify one complete clinic workflow
Test patient registration → edit → encounter/clinical entry → appointment → timeline/audit → export → backup → restore, including validation errors, unauthorized actions, process restart and database failure.

### Phase 5 — Expand deliberately
Only after the core workflow is verified, improve interoperability, operational workflows, sync/exchange, deployment, UI usability and additional modules according to real clinic needs.

### Phase 6 — Release readiness
Run the test suite, build, package, migration and restore checks in a representative environment. Document the supported deployment topology, known limitations, backup recovery procedure, security model and clinical scope.

## Required reporting format

For each phase or change, report:
1. Findings with severity and evidence.
2. Files/routes/tables affected.
3. Changes made and rationale.
4. Tests actually executed and exact results.
5. Data migration/configuration/deployment impact.
6. Remaining risks and unverified assumptions.
7. Next recommended step.

## Definition of done

A feature is not done until its visible control reaches the correct service/API, authorization is enforced, input is validated, data is durably stored, the audit trail reflects the action, errors and partial failures are handled, restart/recovery behavior is known, tests pass, and the UI reports the true persisted outcome.

Do not merge to main or claim production clinical readiness without explicit review. The objective is not the largest feature list; it is a small-clinic system whose behavior, stored data, security controls and documentation can be trusted.
