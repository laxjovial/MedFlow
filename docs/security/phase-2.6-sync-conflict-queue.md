# Phase 2.6 — Durable synchronization conflict queue

## Current implementation

- Schema v7 persists patient sync conflicts, local/remote snapshots, conflicting fields, source device and resolution metadata.
- Conflict fingerprints make repeated pulls idempotent for the same local/remote revision pair.
- Conflict review endpoints require both `sync.manage` and `patients.view`.
- Resolution runs under SQLite `BEGIN IMMEDIATE` using the database transaction context. Patient changes, queue status transition and audit event commit or roll back together.
- Supported decisions: `keep_local`, `apply_remote`, `field_merge`, and `reject`.
- `apply_remote` and `field_merge` require the current patient version to match the local version recorded when the conflict was detected.
- `field_merge` is restricted to an allowlist, only accepts fields recorded as conflicting, and each submitted value must equal the corresponding stored local or remote value. No third, arbitrary clinical value can be introduced through this endpoint.
- Audit records include the actor, conflict ID, patient ID and resolution choice.

## Transaction behavior

`Database.transaction(immediate=True)` holds the shared write lock, begins an immediate SQLite transaction, suppresses per-statement commits, and commits only after the complete operation succeeds. Exceptions roll back the whole operation. Nested transaction failures mark the outer transaction rollback-only.

## Important limitations

- The conflict queue currently covers patient records; other clinical entities are not yet included.
- Field merge is a constrained selection of stored local/remote values, not free-form editing or a semantic clinical merge.
- The API review endpoints exist, but a staff-facing conflict review UI and real desktop-to-server workflow verification remain outstanding.
- Authorization, stale-version checks and atomic rollback have automated coverage; browser-level workflow tests and operational recovery testing remain future work.

## Verification

CI and the full local test suite must pass on the final commit before this phase is considered complete. Intermediate commits in this implementation sequence may have failing checks while dependent changes are being applied.