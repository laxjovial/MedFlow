# MedFlow Baseline Engineering Audit

**Repository:** [laxjovial/MedFlow](https://github.com/laxjovial/MedFlow)  
**Branch reviewed:** `main`  
**Tree snapshot:** `c12df0a1aff8a6bcb3ace2ac132205a16a627bd3`  
**Review date:** 2026-10-29  
**Scope:** Public source tree, README, architecture/roadmap documents, dependency metadata, selected API/security/storage/service/UI/test files.  
**Execution status:** Source inspection only. The repository could not be cloned into the execution environment, so tests, builds, and live runtime behavior have **not** been verified in this review.

## 1. Product identity

MedFlow is best described as a **local-first, offline-capable, self-hosted electronic medical record (EMR) and small-clinic practice-management application**, with a desktop interface and an optional web/API interface sharing SQLite storage.

Its stated core is patient registration and search, clinical chart sections, appointments, reports/exports, audit events, backups, role-based access, temporary scoped access, sync, and inter-facility exchange. The strongest differentiator is data ownership and local operation rather than a vendor-hosted clinic SaaS.

It should not yet be described as a validated production clinical information system solely on the basis of its feature list. Clinical safety, privacy, security, operational recovery, and deployment requirements need evidence from tests and representative use.

## 2. Comparable open-source projects to benchmark

These are reference projects, not proof that MedFlow should copy their architecture wholesale.

| Project | Official repository / docs | What it is strongest at | Transferable lessons for MedFlow |
|---|---|---|---|
| OpenEMR | https://github.com/openemr/openemr | Mature integrated EHR/practice management, scheduling, billing, broad workflows, REST/FHIR and SMART-on-FHIR documentation | Workflow completeness, explicit API contracts, interoperability, deployment/security documentation |
| OpenMRS Core | https://github.com/openmrs/openmrs-core | Extensible EMR platform, flexible clinical data model, concepts/terminology, REST/FHIR, modular extensions | Terminology and coded observations, extensible clinical model, API compatibility, module boundaries |
| Bahmni | https://github.com/Bahmni | Integrated hospital workflows across OpenMRS, laboratory and ERP/inventory systems | Clear integration contracts, lab/operations workflows, low-resource deployment experience |
| Frappe Health | https://github.com/frappe/health (verify current canonical repository before adopting) and https://healthcare.frappe.io/docs | Outpatient/inpatient workflows, appointments, procedures, lab, medical coding and ERP integration | Clinic operations beyond patient CRUD, orders/results, stock/billing integration where justified |
| Medplum | https://github.com/medplum/medplum | FHIR-native developer platform, APIs, identity/authorization, SDKs and server-side workflow automation | Standards-based interoperability, capability discovery, extensible API contracts and automated workflows |
| GNU Health | https://www.gnuhealth.org/ and https://docs.gnuhealth.org/ | EMR/HIS/Hospital Management with a data-ownership and local deployment focus | Facility-owned data, deployment options, broader clinical/administrative workflow boundaries |

**Comparison discipline:** official READMEs and documentation establish stated capabilities, not that every deployment is secure or every feature works. A later deeper competitor audit should pin each repository to a commit/release and inspect code/tests before making source-level security comparisons. Check the current canonical Frappe Health repository and licenses before taking code or dependencies.

## 3. What MedFlow already has worth preserving

The current tree contains meaningful engineering work:

- Desktop launch via `main.py` and an optional FastAPI web/API server.
- SQLite-backed persistence, schema migrations, foreign-key setup and WAL mode.
- Password hashing with Argon2 support and bearer-token authentication.
- A permission vocabulary shared by the web API and desktop session.
- Scoped, time-limited temporary users and invite/onboarding flows.
- Patient soft deletion/restoration and patient-level history/version records.
- Separate audit-event and patient-history concepts.
- Structured clinical records: vitals, diagnoses, medications, allergies, lab results and notes.
- Appointment lifecycle, reports, CSV/JSON exports, local backups and off-site backup support.
- Sync and inter-facility exchange modules with conflict-oriented behavior.
- A substantial test tree spanning unit, integration, server, migration, transfer and UI-import tests.

These are source-level observations. They do not mean all paths have been executed or validated.

## 4. Initial findings and risk register

Severity describes engineering priority based on the inspected source; it is not a statement that an exploit has been demonstrated.

### MF-01 — Two parallel application architectures and conflicting documentation
**Priority: High — maintainability and data-integrity risk**

Evidence:
- `main.py` launches `app.controller.AppController`, which uses `app.storage.Database`, `app.storage.repositories`, and services such as `app.services.patients`.
- `app/main.py` is a separate entry point using `app.container.Container`, `app.repositories.sqlite.*`, and the older `app.services.patient_service` stack.
- Both `app/storage/` and `app/repositories/sqlite/` contain storage/schema/migration code.
- `docs/ARCHITECTURE.md` describes the older `app/domain` + `app/repositories/sqlite` composition, while README describes the newer `app/storage` architecture.
- `docs/ROADMAP.md` lists web/API/auth/network capabilities as future work even though README and current server code describe them as implemented.

Risk: contributors and operators may follow the wrong startup path, migration code, service layer, or instructions. Duplicated business logic can diverge and make fixes apply to one path but not the one users run.

Required next action: establish the canonical entry point and architecture; identify which modules are used by production launch paths, tests and packaging; update docs; only remove legacy paths after import/test evidence proves they are unused and data migration implications are understood.

### MF-02 — Package metadata does not declare the complete runtime
**Priority: High — installation/release risk**

Evidence: `pyproject.toml` declares only `customtkinter>=5.2`, while the runtime includes FastAPI, Uvicorn, Pydantic, Passlib and Argon2. `requirements.txt` includes more dependencies, but `pip install .` alone does not install the server/security dependency set.

Risk: package-based installs may succeed while the web/API or authentication paths fail at runtime.

Required next action: define supported install extras or complete project dependencies, separate runtime and development dependencies, and test clean installation for desktop, server and packaged distributions.

### MF-03 — No repository CI workflow is present in the inspected tree
**Priority: High — regression detection gap**

Evidence: the current tree contains tests but no `.github/workflows/` entries.

Risk: test files can exist without being run for every change. This is especially risky for migrations, permission rules, data exports and clinical record changes.

Required next action: add CI that installs the declared dependencies, runs the full test suite and compile checks, and reports failures. Add lint/type/security checks after their configuration is selected and made reproducible.

### MF-04 — Public authentication endpoints have no visible application-level throttling
**Priority: High when server is reachable by untrusted clients**

Evidence: login, password signup, Google sign-in and pairing redemption are implemented as routes in `app/server/app.py`; no application-level rate-limiting layer was found in the inspected route/dependency path.

Risk: exposed deployments may be susceptible to password guessing, signup abuse or repeated token/pairing attempts. A reverse proxy may provide some protection, but that must be explicitly documented and tested.

Required next action: add bounded per-IP/account throttling and abuse-safe responses, protect first-admin bootstrap against concurrent signup races, and test lockout/availability behavior so an attacker cannot trivially deny service to a legitimate clinician.

### MF-05 — Browser session bearer token is persisted in localStorage
**Priority: High impact if an XSS path exists; hardening required**

Evidence: `app/server/web/workspace.js` stores `medflow.session` in localStorage and sends the token as a bearer header. The UI also uses several `innerHTML` rendering paths; table values commonly pass through `esc()`, but every dynamic rendering path must be checked.

Risk: any successful script injection in the same origin could read the stored token. This is a defense-in-depth concern, not proof that an exploitable XSS is present.

Required next action: audit all dynamic HTML insertion paths and consider an HttpOnly, Secure, SameSite cookie-based web session with CSRF protection where appropriate. Keep desktop bearer-token pairing as a separately reviewed client flow.

### MF-06 — Deployment security depends on host/TLS configuration
**Priority: High for networked deployment**

Evidence: the server defaults to `127.0.0.1`, but accepts a configurable host; the built-in Uvicorn startup does not itself configure TLS.

Risk: binding to a non-loopback interface without a correctly configured HTTPS reverse proxy can expose bearer tokens and sensitive clinical data over the network.

Required next action: document local-only defaults, warn/refuse unsafe non-loopback production configurations unless an explicit override is supplied, and provide a hardened HTTPS deployment recipe. Verify firewall, proxy, cookie, header and backup permissions in a representative deployment.

### MF-07 — Public health endpoint discloses facility name and patient count
**Priority: Low to Medium depending on exposure**

Evidence: `GET /api/health` is public and returns facility name plus patient count.

Risk: exposes operational metadata unnecessarily to unauthenticated callers.

Required next action: make public liveness minimal (e.g. `ok` only), move detailed readiness/metrics behind authorization or a trusted network, and test both paths.

### MF-08 — Feature breadth exceeds verified end-to-end evidence
**Priority: High — release confidence gap**

Evidence: the repository includes sync, exchange, cloud backup, automation, invites, notifications and many clinical endpoints, while the current review could not execute the tests or exercise the app. The README describes all current planned functionality as implemented, but the older roadmap disagrees.

Risk: a UI control or documented capability may be incomplete, disconnected, or fail on restart/partial failure even if its helper function exists.

Required next action: create a traceability inventory for every visible action: UI handler → API/service → repository/schema → permissions → audit → test → error/empty/loading behavior. Use contract and end-to-end tests for the highest-risk flows.

### MF-09 — Clinical semantics and interoperability need explicit boundaries
**Priority: Medium — capability gap, not necessarily a defect**

Evidence: MedFlow has structured record sections and a patient exchange format, but the reviewed API and docs do not establish full FHIR resource compatibility or a terminology service comparable to mature platforms.

Risk: ad hoc JSON/CSV/bundle formats can be useful locally but limit safe integration and semantic exchange with other healthcare systems.

Required next action: define a versioned internal clinical model, map a deliberately small initial set of resources to a recognized FHIR version (e.g. Patient, Encounter, Observation, Condition, AllergyIntolerance, MedicationStatement/Request as appropriate), and add round-trip/validation tests. Do not claim FHIR compliance before conformance testing.

### MF-10 — No license file or repository license metadata was present
**Priority: Medium — adoption and reuse risk**

Evidence: GitHub repository metadata reported no license, and the root tree contained no `LICENSE` file.

Risk: users and potential contributors cannot infer permission to reuse, modify or redistribute the project from public availability alone.

Required next action: choose a license deliberately, considering the intended use and dependencies, then add the license file and metadata. Do not copy code from comparison projects without checking their license obligations.

## 5. Security controls observed (positive findings)

- Most inspected patient, clinical-record, appointment, export, backup and settings routes require a bearer token and call a permission check.
- The current-user dependency loads the user from storage for each request, so role changes/deactivation can take effect without trusting the role claim in an old token.
- Passwords are hashed using Argon2, with bcrypt support for migration.
- SQLite foreign keys and WAL are configured by the active storage engine.
- Off-site backup credentials are described as write-only and stored separately from ordinary configuration.
- The web client escapes table cell values through an `esc()` helper in the inspected generic table renderer.
- Tests cover protected routes, patient workflows, clinical record endpoints, appointments, exports, exchange and storage/migrations.

These are useful controls, but no security control should be marked fully verified until its failure paths are tested.

## 6. Recommended implementation order

1. **Baseline and truth:** make CI run; record actual test results; create the UI-to-backend feature inventory; identify canonical startup, storage and migration paths.
2. **Security gates:** throttle authentication/pairing, protect initial-admin bootstrap, review XSS sinks/token storage, harden network deployment, minimize public health metadata.
3. **Data integrity:** test all schema migrations from representative legacy databases; verify backup/restore by reopening and querying restored data; verify sync/exchange idempotency and conflict behavior.
4. **End-to-end clinic workflow:** register patient → edit demographics → create encounter/clinical entries → schedule/complete appointment → view timeline/audit → export/backup → restore and verify.
5. **Clinical quality:** define encounter model, clinical terminology/coding strategy, medication/lab lifecycle and audit semantics; avoid treatment recommendations or automated clinical decisions without appropriate clinical governance.
6. **Interoperability:** implement a scoped, validated FHIR mapping and test it against fixtures/validators before expanding.
7. **Release engineering:** clean-install tests, package builds, version/license consistency, migration/recovery guide, threat model and release checklist.

## 7. Acceptance criteria for the first complete workflow

- Every visible action maps to a real handler and an implemented service/API operation.
- Invalid input is rejected before persistence with field-level feedback.
- Permission-denied requests do not mutate data.
- Each successful clinical mutation is persisted and auditable.
- A failed operation does not leave partial records or falsely report success.
- Restarting the application preserves the expected state.
- A backup can be restored into a test environment and key records/counts are verified.
- Exported records are scoped to the authorized user and escaped/serialized safely.
- Tests cover success, validation failure, authorization failure, duplicate request, database error and restart/recovery.
- Documentation describes only behavior verified by tests or clearly labels unverified behavior.

## 8. Review limitations

This report is a baseline source inspection, not a penetration test, clinical safety assessment, regulatory certification, or test-run report. It does not prove that an attack is exploitable, nor that an unmentioned risk is absent. The next pass must execute tests and inspect each critical route/service/UI path with stable file/line evidence.


### MF-11 — Version metadata is inconsistent
**Priority: Medium — release and support risk**

Evidence: `pyproject.toml` declares version `2.0.0`, while `app/__init__.py` declares `__version__ = "3.0.0"`. The repository's previous release notes/tags also need to be reconciled with these values before packaging.

Risk: bug reports, built artifacts, package metadata and in-app diagnostics may identify different versions, making it harder to determine which code a clinic is running.

Required next action: choose one authoritative version source, wire packaging/build metadata to it where practical, and add a release check that fails when published version identifiers disagree.
