---
name: medflow-engineering
description: Audit, implement, and verify MedFlow healthcare workflows with a focus on clinical data integrity, privacy, security, persistence, and truthful UI behavior.
---

# MedFlow Engineering Skill

## When to use this skill

Use for any change to MedFlow's desktop UI, web client, API, patient records, clinical charting, appointments, identity/access, storage, migrations, backups, sync, exchange, reports, packaging, documentation, or deployment.

## Non-negotiable principle

Trace each user-visible action through the real implementation to durable, verified state. A button, route, service, schema, or test file is not proof that a feature works.

MedFlow handles sensitive health information. Prefer data integrity, confidentiality, recoverability, clinical clarity, and honest limitations over feature count or visual polish.

## 1. Establish the baseline

- Inspect the Git state, current branch, default branch, recent history, and uncommitted work before editing.
- Read the current README, architecture, roadmap, dependency metadata, launchers, packaging spec, configuration, schema/migrations, services, repositories, API routes, UI callbacks, and relevant tests.
- Identify the canonical launch path used by users and the paths actually exercised by CI/tests.
- Search for duplicate implementations, stale modules, unregistered routes, unused helpers, TODOs, mismatched dependencies, and conflicting documentation.
- Never delete a legacy path until its imports, data format, migration path, tests, and packaging references have been checked.

## 2. Build a feature traceability record

For every visible control or advertised capability, record:

1. User goal and UI control.
2. Event handler/callback.
3. API route or desktop controller method.
4. Authentication and permission check.
5. Service/business rule.
6. Repository and database tables/constraints.
7. Audit/history event.
8. Success, validation, empty, loading and failure behavior.
9. Tests that verify the behavior.
10. Restart, backup/restore, migration and concurrency behavior where relevant.

Classify each item as **verified**, **partially implemented**, **missing**, **broken**, **unverified**, or **blocked**. Do not use “implemented” where only a UI or helper exists.

## 3. Clinical data integrity

- Validate input at boundaries and again in the domain/service layer.
- Use parameterized SQL, database constraints, transactions and foreign keys.
- Keep clinical history separate from security/audit history.
- Preserve provenance: who entered or changed a record, when, from which device/source, and which fields changed.
- Never silently overwrite conflicting clinical data. Use explicit conflict reports and human review for ambiguous merges.
- Distinguish patient demographics, encounters, observations/vitals, conditions/diagnoses, medication records, allergies, orders/results, appointments and notes. Do not collapse a longitudinal chart into a single free-text field.
- Avoid deriving clinical advice, diagnoses, or treatment recommendations from application logic without a separately defined clinical safety and validation process.
- Treat critical lab flags as workflow signals, not as a substitute for clinician judgment.
- Keep test fixtures synthetic; never commit real patient records, backups, logs or exported data.

## 4. Identity, privacy and security

- Enforce authentication and authorization server-side for every sensitive route and action. Hiding a button is not authorization.
- Test each role against allowed and denied operations, including temporary users and patient-scoped access.
- Protect login/signup/pairing against brute force and abuse while avoiding lockouts that can deny a clinic access.
- Protect first-admin bootstrap from race conditions.
- Never return raw secrets or password hashes; keep tokens, keys, passwords, cookies and clinical contents out of logs.
- Review browser storage and all dynamic HTML insertion paths for XSS impact. Prefer safe DOM APIs and context-appropriate escaping.
- Use HTTPS for networked deployments; do not expose the server on public interfaces without a documented reverse proxy/TLS and firewall configuration.
- Apply least privilege to export, restore, sync, user management and cloud-backup operations.
- Validate off-site backup endpoints, redirect behavior and protocol configuration; do not allow an untrusted user to turn the server into a network-fetch proxy.
- Define retention, deletion, export, backup, key rotation and recovery behavior.
- Do not claim HIPAA, GDPR, NDPR, FHIR or other compliance/conformance without a scoped assessment and evidence.

## 5. Persistence, migrations and recovery

- Identify the active schema and migration runner before changing tables.
- Make migrations ordered, repeatable where appropriate, transactional where supported, and tested against old-version fixtures.
- Back up before destructive or irreversible data operations.
- Verify restore by reopening the restored database and asserting integrity and representative record counts/values.
- Use uniqueness constraints and idempotency where retries could create duplicate patients, events, appointments, transfers or sync changes.
- Test concurrency and SQLite lock behavior under the expected local/network topology.
- Do not assume a SQLite file on a network share is safe for multi-host concurrent writes. Recommend a supported deployment topology and document limitations.
- Make failures visible; never return success after a partial write unless partial success is explicitly represented and reconciled.

## 6. Clinical workflows and UI integrity

- Test the full workflow, not just each helper independently.
- For each form, verify required fields, ranges, cross-field rules, keyboard behavior, cancellation, duplicate submissions, stale views and error messages.
- Confirm edits persist after closing and reopening the record/application.
- Ensure the UI refreshes from persisted state and doesn't display optimistic success that storage rejected.
- Check every action for permission visibility **and** server-side enforcement.
- Keep clinical terminology understandable; display units, timestamps, source and status where necessary.
- Do not add placeholder/inert buttons. Hide incomplete features or label them honestly.

## 7. Interoperability and external systems

- Prefer documented standards and APIs. Treat custom JSON/CSV/transfer bundles as MedFlow-specific formats unless validated otherwise.
- Version exchange formats and validate imported content before writes.
- Never auto-merge possible duplicate patients without an explicit review step.
- If implementing FHIR, select a version and implementation scope, map fields explicitly, use recognized terminology where possible, and test against validators/fixtures. Do not call an ad hoc JSON bundle “FHIR-compliant.”
- Test import/export round trips, invalid bundles, checksums, duplicate IDs, partial failure, rollback and audit records.

## 8. Testing and release evidence

Add or update focused tests for every defect. Cover:
- valid and invalid input;
- unauthorized and wrong-role access;
- malformed tokens and expired/revoked users;
- database constraints and migration paths;
- duplicate requests and concurrent operations;
- backup, restore and integrity checks;
- export scope and escaping;
- sync/exchange conflicts and retries;
- UI callbacks and API/UI state parity;
- clean installation, packaging and startup.

Run tests and report actual command/output. If execution is unavailable, say so and provide the exact command and environment needed. Never say “all tests pass” without evidence.

## 9. Safe implementation method

- Prefer small changes that fix root causes over broad rewrites.
- Work on a feature branch; preserve the current main branch.
- Write acceptance criteria before implementing high-risk workflows.
- Update documentation and tests with behavior changes.
- Keep migrations and compatibility in scope.
- Avoid new dependencies unless they solve a demonstrated need and are maintained.
- Do not commit or deploy real patient data.
- Do not merge to main, publish a release, or represent MedFlow as clinically production-ready without explicit review and evidence.

## 10. Completion report

Every change report must include:
- What changed and why.
- Exact files/routes/schema affected.
- Tests actually run and results.
- Migration/configuration/deployment implications.
- Known limitations and unresolved risks.
- Whether the visible feature was traced end to end.
- The next smallest high-value step.

## Definition of done

A feature is done only when the UI/API, permissions, business rules, persistence, audit trail, errors, recovery, tests, and documentation agree about what happened. If any layer is unverified, state that limitation explicitly.
