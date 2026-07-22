# Operator Migration Review Workflow

The workflow is governance-only: immutable proposal → explicit review → decision → immutable review record → stop. Reviews do not activate accounting, create lots or opening snapshots, publish generations, create pointers, or modify legacy data.

Reviews support `PENDING`, `APPROVED`, `REJECTED`, `CHANGES_REQUIRED`, and `EXPIRED`. Every record requires reviewer identity, timestamp, rationale, supporting reference, and a digital-signature placeholder. It binds the proposal hash, approval-pack ID/hash, evidence-pack hash, repository commit, and schema version. Any change to those dependencies invalidates the review automatically.

History rejects duplicate immutable review IDs and is ordered by timestamp. The latest valid review per proposal drives metrics for pending, approved, rejected, changes required, expired, unresolved critical/high materiality, and approval completeness.

The deterministic export bundle contains review records, all proposal hashes, approval-pack and evidence hashes, repository commit, creation timestamp, state summary, and bundle hash. Export returns serialized content only; there is no automatic import or production writer.

The authenticated Operations page is read-only and has no approve/reject buttons. Operators make explicit decisions through the offline Python governance interface, retain supporting evidence externally, verify hashes, and re-review whenever dependencies change. A future opening-snapshot workflow remains separate and unavailable until all evidence and governance blockers are resolved.
