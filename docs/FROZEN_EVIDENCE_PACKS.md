# Frozen Evidence Packs

Frozen Evidence Packs are immutable governance artifacts only. They do not activate accounting, create an Opening Snapshot Candidate, create migration lots or generations, move a production pointer, or change cash, positions, P&L, risk, scheduling, or execution.

## Lifecycle

An operator explicitly selects authoritative documents and supplies their source identity, timestamps, type, coverage, confidence, verification state, gap links, and optional normalized records. Collection reads only those paths; it performs no source discovery and makes no inference. Missing fields stay unknown.

The freeze lifecycle is: collect evidence, validate, calculate coverage, preserve the existing Gap Register, freeze a new version, then stop. A staging directory is fully written and hash-verified before one atomic directory rename. Existing versions cannot be updated or reused. Interrupted creation removes staging data and leaves prior versions unchanged.

Supported evidence classes are broker statements, trade confirmations, cash statements, dividend statements, corporate actions, FX records, tax statements, and manual operator documents. Normalized records use the existing facts without filling gaps: trade, cash movement, dividend, fee, tax, FX conversion, corporate action, or adjustment. Original documents are retained byte-for-byte with checksums.

## Identity and coverage

Every item has a stable identifier and checksum. An identical duplicate is idempotent; conflicting content under the same identifier fails closed. Only `VERIFIED` evidence contributes to strategy, FIFO, position, cash, dividend, FX, fee, tax, or corporate-action coverage. Unverified, rejected, missing, and explicitly unknown facts do not raise coverage. Overall coverage is the equally weighted mean of those nine published measures; unknown coverage is its complement.

Evidence is linked to existing gaps and migration proposals by immutable gap IDs. The frozen manifest binds the source Evidence Pack hash, optional existing Approval Pack hash, repository commit, timestamps, proposal links, artifact hashes, and bundle hash. It introduces no approval or review model. A later evidence change requires a new frozen version and therefore invalidates hash-bound review records through the existing workflow.

## Operator workflow

1. Place authoritative source documents in a controlled operator location outside source control.
2. Construct typed `EvidenceDocumentRequest` values and normalized records from documented facts only.
3. Verify source authority and explicitly link each item to existing Gap Register IDs.
4. Build the existing evidence and migration packs at one explicit cut-off.
5. Call `freeze_evidence_pack` with a new positive version, repository commit, cut-off, and collection.
6. Independently load and export the pack; compare the manifest and bundle hashes before review.

There is intentionally no dashboard write action and no automatic import. The deterministic export is JSON containing the manifest and hashes, coverage, Gap Register, evidence inventory, repository commit, creation timestamp, schema version, and export hash. The dashboard loads the highest unique frozen version and reports `NOT_FROZEN` when none exists; it never regenerates evidence during a read.

Future Opening Snapshot work may consume an explicitly reviewed frozen version. It must continue to treat missing strategy ownership, FIFO evidence, acquisition FX, cash history, dividends, fees, taxes, and corporate actions as unknown until authoritative evidence is supplied and separately approved.
