# Shadow research operations

## 1. DOCUMENT STATUS

Document version: `1.0`
Reviewed HEAD: `a66f3df059892cf3266247a0422a889717eb3a38`
Phase F commit range: `5abc0a4d4deb34a2a88687da77c8d36eb5932444..a66f3df059892cf3266247a0422a889717eb3a38`
Classification: `shadow_observation_unverified`

This is a research-only operating document. It is not investment advice and is
not approved for production capital.

## 2. PURPOSE

The shadow layer compares caller-supplied validated research decisions and
their evidence with explicitly supplied legacy observations. It observes
agreement and difference without validating the legacy methodology. It does
not control, replace, or otherwise alter the active production path.

## 3. AUTHORITATIVE DATA FLOW

1. A caller supplies validated evidence as immutable `StrategyDecision`
   contracts.
2. A caller supplies versioned legacy observations.
3. The shadow runner validates identities and the information cutoff.
4. `compare_shadow_observations` produces per-instrument,
   dimension-level outcomes.
5. `run_shadow_comparison` returns an immutable in-memory result.
6. Nothing is automatically saved, published, executed, or notified.

## 4. LEGACY SOURCE CLASSIFICATION

The inspected legacy sources are classified as follows:

- `signal_report_v2.csv` is usable only for limited shadow signal and weight
  comparison. It has explicit date, ticker, signal, weight, and status fields,
  but has no historical availability timestamp.
- `holdings_report.csv` is a mutable operational/paper projection. It is
  usable only with limitations and lacks execution provenance.
- Aggregate portfolio and paper trackers are unsuitable for per-instrument
  decision comparison.
- Accounting evidence is not quantitative validation.

Missing timestamps, currency, unit, and provenance remain unavailable; the
shadow contracts do not infer them.

## 5. LEGACY OBSERVATION CONTRACTS

`research.legacy_observations` exposes the immutable contracts
`LegacySignalObservation`, `LegacyWeightObservation`,
`LegacyPortfolioProjection`, `LegacyObservationSet`, and `LegacyParseResult`,
plus `parse_signal_report_csv`.

`parse_signal_report_csv(text, *, source_artifact_hash, parser_version,
weight_unit, methodology_classification="legacy_methodologically_invalid")`
accepts caller-supplied CSV text only. It does not open repository files. The
caller supplies the source artifact hash, parser version, declared weight unit,
and legacy methodology classification. Parsed observations retain the supplied
source hash, schema version, parser version in `LegacyParseResult`, raw field
provenance, limitations, and the unverified classification.

Numeric CSV values are parsed as `Decimal`; empty numeric values remain
`None`, not zero. Missing timestamps, currency, price unit, and other absent
fields remain unavailable. Canonical hashes provide deterministic identities.
The signal parser rejects malformed headers, rows, dates, decimals, and
duplicate `(ticker, date)` identities by returning a `LegacyParseResult` with
`status="rejected"`. `LegacyObservationSet` rejects duplicate
`(legacy_source_type, source_row_id)` identities. No parser or contract opens
a repository artifact automatically.

Supported classifications are fixed by `CLASSIFICATIONS`; they include
`legacy_methodologically_invalid`, `legacy_unverified`,
`paper_observation_unverified`,
`operational_evidence_not_quantitative_validation`, and
`accounting_evidence_not_quantitative_validation`. The unverified
classification is retained rather than promoted by parsing.

## 6. COMPARISON CONTRACT

`research.shadow_comparison` exposes `ShadowComparisonPolicy`,
`ShadowDifference`, `InstrumentComparison`, `ShadowComparisonSummary`, and
`compare_shadow_observations(*, validated_decisions, legacy_signals,
legacy_weights=(), policy)`.

The implemented per-instrument dimensions are `instrument_eligibility`,
`signal_direction`, `decision_status`, `target_weight`, `timing`,
`currency_unit` (or the more specific `currency` and `price_unit`), and
`methodology`. Instrument eligibility distinguishes unmatched validated and
legacy observations. Signal direction compares legacy positive, negative, or
neutral signal with validated decision direction. Status and declared weight
are compared when available. Timing, currency, and price unit require explicit
legacy values.

`LegacyWeightObservation` can carry `notional`, `quantity`, and `price`, but
the current `compare_shadow_observations` implementation does not compare
intended notional, quantity, or price. Those fields therefore produce no
comparison claim. Legacy exclusions and their reasons are applied by the
runner before comparison and appear as unavailable input records, rather than
as an automatic performance or execution decision.

`OUTCOMES` permits only `agree`, `differ`, `unavailable`, `incomparable`,
`excluded`, `legacy_only`, `validated_only`, `timing_mismatch`,
`unit_mismatch`, `currency_mismatch`, and `methodology_mismatch`. The current
comparison path emits the applicable agreement, difference, availability,
unmatched, timing, unit, currency, and methodology outcomes; it does not
invent an outcome for absent comparisons.

Agreement does not validate legacy methodology. Disagreement does not prove
profitability or superiority. Difference counts are not performance metrics.

## 7. SHADOW RUNNER

`research.shadow_runner` publicly exports `RESULT_CLASSIFICATION`,
`SCHEMA_VERSION`, `ShadowRunRequest`, `ShadowRunResult`, `canonical_sha256`,
`validated_evidence_identity`, and `run_shadow_comparison(request)`.

`ShadowRunRequest` requires a supported request schema and policy, UTC
timestamps, nonblank identity fields, a nonempty immutable tuple of validated
`StrategyDecision` values, and the exact identity from
`validated_evidence_identity`. It accepts caller-supplied
`LegacyObservationSet` data (or `None`), plus warnings and limitations. Its
documented compatibility aliases are `validated_evidence_bundle`,
`validated_evidence_hash`, `parameter_version`, `code_revision`, and
`legacy_observation_set`; conflicts fail closed.

The runner validates the request and validated evidence identity before using
legacy data, validates legacy identities, excludes parsed legacy observations
after the explicit information cutoff, rejects validated decisions whose
decision or information-cutoff timestamp is after that cutoff, then compares
the remaining observations. A future or non-parsed legacy observation is
reported in `unavailable_inputs`; a missing legacy set is also unavailable.
Conflicting legacy identities, unsupported types, schemas, or policies fail
closed. Invalid validated evidence cannot fall back to legacy evidence.

The request normalizes validated decisions by instrument and decision ID;
conflicting duplicate identities fail. Result comparisons, warnings,
limitations, and unavailable inputs are sorted deterministically. Canonical
JSON bytes and SHA-256 values are deterministic, and equivalent input order
does not change the result identity. `ShadowRunResult` is frozen and contains
no persistence operation.

## 8. HARD SAFETY CONTRACT

Every `ShadowRunResult` fixes these fields:

- `result_classification="shadow_observation_unverified"`
- `execution_authorized=false`
- `publication_authorized=false`
- `runtime_effect=false`
- `paper_effect=false`
- `accounting_effect=false`

Callers cannot override these fields.

## 9. PROHIBITED CAPABILITIES

The runner has no API for order submission, paper-portfolio update, risk
authorization, ledger or accounting commit, notifications, Supabase writes,
filesystem publication, scheduler registration, dashboard mutation, or runtime
control.

## 10. OPERATIONAL STATUS

There is no CLI, service, scheduler, dashboard page, automatic persistence,
production import, or deployment for the shadow runner. At this checkpoint,
Phase F exists only in the local branch. Production deployment remains
manual-only.

## 11. FUTURE MANUAL USE

A future operator-controlled process would provide an explicit validated input
bundle, explicit legacy source hash, and explicit information cutoff; run a
read-only comparison; review unavailable and incomparable outcomes; and make
no state mutation. This document supplies no command that starts production
modules.

## 12. FUTURE PERSISTENCE GATE

Before any shadow report may be saved, separate authorization must define an
explicit output root, immutable content manifest, exact namespace membership,
tamper verification, retention policy, privacy review, and operator ownership.

## 13. FUTURE SCHEDULING GATE

Before scheduling, separate approval must establish bounded resource use,
failure isolation, remote health visibility, alert design, an incident
procedure, no production-state mutation, and independent review.

## 14. TRADING-INFLUENCE GATE

Before a shadow result may influence trading, a separate explicit phase must
cover independent validation, broker sandbox work, order lifecycle, partial
fills and rejection handling, accounting reconciliation, approved risk limits,
kill-switch integration, deployment controls, and explicit owner
authorization.

## 15. TEST EVIDENCE

Recorded focused TKT-039 evidence:

`29 passed`

Recorded approved remediation suite:

`172 passed, 1 skipped, 32 subtests passed`

No skip reason is recorded here because one was not established from the
approved remediation output or the Phase F test source. The remediation-added
tests construct caller-supplied immutable decisions, CSV text, source hashes,
and legacy observation sets in memory; they exercise parsing, deterministic
hashing, cutoff handling, safety fields, and static import/capability
isolation. The Phase F test files are `tests/test_legacy_observations.py`,
`tests/test_shadow_comparison.py`, and `tests/test_shadow_runner.py`.

The baseline manifest SHA-256 is
`E634DCFEB8AFE5A847CA29C529C19BD88AC2B9711B7161694EC4D1CA36CF89D8`.
It inventories 47 artifacts, including 30 immutable artifacts. This is not a
claim that a broad legacy repository test suite passed.

## 16. PHASE F COMMITS

The completed Phase F commits before this document commit are:

1. SHA `1e41ae75a501ea0f9a973a5c974c674cd72a00a8`; parent
   `5abc0a4d4deb34a2a88687da77c8d36eb5932444`; message
   `feat: add versioned legacy observation contracts`; files
   `research/legacy_observations.py` and `tests/test_legacy_observations.py`.
2. SHA `f020a6cc301b788d7330bcd48be24189c7f89daf`; parent
   `1e41ae75a501ea0f9a973a5c974c674cd72a00a8`; message
   `feat: add explainable shadow comparison`; files
   `research/shadow_comparison.py` and `tests/test_shadow_comparison.py`.
3. SHA `a66f3df059892cf3266247a0422a889717eb3a38`; parent
   `f020a6cc301b788d7330bcd48be24189c7f89daf`; message
   `feat: add non-authoritative shadow research runner`; files
   `research/shadow_runner.py` and `tests/test_shadow_runner.py`.
4. This document commit; parent
   `a66f3df059892cf3266247a0422a889717eb3a38`; message
   `docs: define shadow research operations`; file
   `docs/shadow_research_operations.md`.

This document is not amended to insert its own final SHA.

## 17. DEPLOYMENT SAFETY

Automatic push deployment is disabled. The deployment workflow requires
`workflow_dispatch`. Phase F was not pushed and no deployment occurred. No
active module imports the shadow runner.

## 18. LIMITATIONS

The shadow layer has no automatic market-data acquisition, historical
point-in-time fundamental dataset, live shadow schedule, remote persistence,
dashboard presentation, or broker comparison. Legacy timing, unit, currency,
and provenance are incomplete. Active legacy defects remain. There is no
validated performance claim, backtest/paper parity claim, or
production-capital approval.
