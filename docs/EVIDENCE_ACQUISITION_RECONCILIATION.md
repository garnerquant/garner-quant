# Authoritative Evidence Acquisition and Reconciliation

This pipeline improves evidence quality only. It does not activate canonical accounting, construct an Opening Snapshot Candidate or migration lot, publish a generation, move a pointer, or modify historical accounting.

## Acquisition lifecycle

An operator selects a document from a controlled source and chooses its typed adapter: broker trade statement, broker account statement, cash statement, dividend statement, FX confirmation, corporate-action notice, tax document, or manual operator evidence. The import request requires source identity, stable identifier, statement period, issue date, explicit import timestamp, confidence, verification state, existing Gap Register links, and any normalized facts. The original bytes, SHA-256 checksum/document hash, coverage, and metadata are retained in the frozen pack.

Adapters do not parse ambiguous documents or invent normalized facts. Normalized values must be supplied from authoritative fields. Missing strategy identity, FIFO association, acquisition FX, cash movement, dividend, fee, tax, interest, or corporate-action terms remain unknown.

## Reconciliation lifecycle

Records are grouped by explicit record type and stable source record ID. Two or more independent verified sources with identical normalized fields produce `EXACT_MATCH`. A single source or unverified corroboration produces `PARTIAL_MATCH`. Differing fields produce `CONFLICT`. Required or source-declared unknown fields produce `UNKNOWN`; absent evidence categories are listed as `MISSING` documents.

Trade-to-position, trade-to-lot, and lot-to-cash relationships are returned only when the source supplied those associations and independent verified records match. The pipeline never reconstructs a missing relationship. Cash reconciliation separately reports deposits/withdrawals and other cash movements, dividends, fees, taxes, FX conversions, and corporate adjustments. Interest remains an explicit cash movement category; it is never derived from balance changes.

## Gaps, confidence, and coverage

Evidence remains linked to the existing Gap Register, migration proposals, Approval Pack, and Review Workflow. A gap is `RESOLVED` only when every linked reconciliation result is an exact match between independent verified sources. Any disagreement makes it `CONFLICT`; missing, partial, unverified, or unknown evidence leaves it `OPEN`. These are evidence outcomes, not operator approvals or accounting decisions.

Only exactly reconciled, verified evidence contributes to updated coverage. Published metrics are strategy, FIFO, position, cash provenance, dividend, FX, fee, tax, corporate action, overall, and unknown coverage. Strategy coverage additionally requires an explicit `strategy_id`; association with a position alone is insufficient. Each new pack records changes from the explicitly supplied previous frozen pack.

## Pack update and export

The operator freezes reconciliation into a new positive pack version. The prior directory is never modified. The new immutable manifest binds the prior pack ID, repository commit, cut-off, source Evidence Pack, existing Approval Pack, evidence documents, coverage changes, gap states, reconciliation hash, artifact hashes, and bundle hash. Failed creation removes only staging data.

The deterministic export includes evidence inventory, reconciliation/conflict report, coverage and trend report, Gap Register, frozen manifest, hashes, and export hash. Export does not import, approve, or publish anything. Operations reads this frozen history to show current/previous packs, coverage improvement, resolved/open gaps, conflicts, confidence, and import history; it has no write controls.

A future Opening Snapshot Dry Run may use a separately reviewed frozen version only after all blocking unknowns and conflicts have authoritative resolution. No automatic reconciliation outcome authorizes that future step.
