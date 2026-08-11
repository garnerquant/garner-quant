# Validated research methodology

## Scope and status

This document describes the offline, non-production research path exercised by
Phase E. It is an evidence and engineering methodology, not a claim that any
strategy is profitable, decision-grade, production-ready, or suitable for live
capital. Research outputs remain exploratory and unverified unless a future
independent review explicitly establishes otherwise.

The path is intentionally disconnected from providers, runtime scheduling,
paper execution, broker integrations, accounting publication, and dashboard
state. It consumes caller-supplied datasets, metadata, universe memberships,
fundamental observations, corporate actions, and information cutoffs.

## Temporal controls

Every research run has explicit dataset, universe, parameter, strategy,
execution-model, cost-model, code-revision, and information-cutoff provenance
in `research/run_manifest.py` and `research/validated_pipeline.py`.

The technical-only mode (`research/technical_only.py`) requires completed bars
and an information cutoff. Point-in-time fundamental selection
(`research/evidence_mode.py`) accepts only observations available by the
cutoff. Universe selection (`research/universe_selection.py`) uses explicit
membership validity dates and rejects assets that are not eligible at the
decision date. Corporate actions are supplied as dated observations rather
than inferred from current state.

The Phase E temporal tests cover future-bar rejection, future fundamental
rejection, as-of universe selection, stale-data fail-closed behaviour, and
production-path isolation. These tests do not prove that external provider
data is historically point-in-time; that remains a data-acquisition and
provenance obligation for callers.

## Dataset and strategy boundary

`research/validated_dataset.py` defines the immutable dataset boundary and
records the price basis, frequency, quality policy, instrument metadata
identity, creation time, and information cutoff. Strategy decisions are
represented by the existing immutable contracts in `strategy/contract.py` and
serialized by `strategy/serialization.py`.

Research modes are explicit:

* `technical_only_historical_v1` is the safe interim historical baseline when
  dated fundamental observations are unavailable.
* `point_in_time_fundamental_v1` requires caller-supplied dated observations
  and applies the availability cutoff.

No mode silently substitutes current fundamentals for historical dates.
Results are classified as `exploratory_unverified` by the research bundle.

## Accounting and execution identities

The Phase E accounting tests use exact `Decimal` arithmetic and assert:

* chained returns equal the product of period factors;
* FX conversion and inverse conversion round-trip at the stated precision;
* split, dividend, and symbol-change events conserve the represented
  quantity/value according to their explicit event semantics;
* execution gross value, fees, and cash movements have consistent signs;
* equity, cash, current-equity sizing, and drawdown identities agree.

These are internal consistency checks, not evidence of economic profitability.
They do not model every market-impact, tax, liquidity, or broker constraint.

## Determinism and publication

Research bundles use canonical JSON bytes and SHA-256 integrity identifiers.
Repeated construction with identical inputs must produce identical bytes and
hashes. Meaningful input changes must change the integrity identifier. Output
publication is directed to an explicit root outside the repository and uses a
temporary-file plus atomic-replace pattern.

Each publication namespace contains exactly:

* `bundle.json`, whose byte size and SHA-256 are declared; and
* `content_manifest.json`, the publication content manifest.

The content manifest intentionally does not self-declare. Verification in
`research/validated_pipeline.py` now constructs the declared and actual
namespace sets and requires exact membership. It rejects missing or
unexpected files, directories, leftover temporary files, symbolic links and
other non-regular entries, duplicate declarations, case-colliding paths,
malformed metadata, invalid hashes/sizes, and unsafe absolute, UNC, drive,
separator, or parent-traversal paths. Declared content is checked by exact
byte size and SHA-256.

## TKT-035 publication-verification defect and correction

The first TKT-035 attempt exposed a fail-open defect: `verify_publication()`
checked the declared `bundle.json` but did not compare the actual directory
contents with the authorized membership. An undeclared `unexpected.json`
therefore verified successfully.

TKT-035A corrected this in commit `2c76285c22d3eac967bada14d0ab94114cf906fe`
(`fix: reject unexpected research publication files`). The corrective tests
cover valid and idempotent publication, unexpected regular/hidden/temporary
files, unexpected directories, missing and modified content, size/hash
mismatches, duplicate and case-colliding declarations, traversal and absolute
path forms, malformed manifests, invalid metadata, and symlink rejection where
the host permits safe symlink creation.

Verification is deliberately fail-closed and returns `False` for ordinary
invalid evidence rather than leaking parsing or filesystem errors. The
implementation is a safely testable boundary, not a claim of protection
against every Windows native-handle attack, filesystem race, or concurrent
mutation between inspection and consumption.

## Evidence publication controls

Publication is research-only and non-executable. It must not overwrite a
conflicting existing publication, and it must not write legacy production
result names such as `trade_log.csv`, `portfolio_v2.csv`, or
`fundamental_scores.csv`. The cross-module determinism test confirms repeated
construction, ordering invariance, meaningful hash sensitivity, tamper and
membership detection, path-boundary rejection, and production import
isolation.

The publication manifest records provenance and integrity; it is not a backup
and cannot recover prior contents. Historical quantitative results in the
baseline evidence manifest retain their existing legacy/unverified status.

## Test record

The final approved Phase E suite was run offline with cache generation
disabled and a temporary test root. The final result was:

`143 passed, 1 skipped, 32 subtests passed`

The single skip is the symlink-specific regression case when the Windows test
environment does not permit symlink creation. General unexpected-file,
directory, malformed-manifest, and hash/size tests remain mandatory and pass.

The five Phase E commits, in order after the original Phase E starting commit,
are:

1. `11755f1` — `test: enforce temporal research invariants` —
   `tests/test_research_temporal_invariants.py`
2. `113c5db` — `test: enforce quantitative accounting identities` —
   `tests/test_quantitative_accounting_invariants.py`
3. `2c76285` — `fix: reject unexpected research publication files` —
   `research/validated_pipeline.py`,
   `tests/test_validated_research_pipeline.py`
4. `0d256cb` — `test: verify deterministic research evidence chain` —
   `tests/test_research_cross_module_determinism.py`
5. TKT-036 — `docs: define validated research methodology` — this document.

The first two commits were completed before the publication defect was found;
the third is intentionally a separate transparent corrective commit. No
commit was amended, squashed, reset, or rewritten.

## Promotion boundary and remaining work

Passing these tests does not promote a strategy to paper or live execution.
Before any such consideration, the project still requires independent review
of provider data provenance, point-in-time fundamentals and universe history,
execution realism, liquidity and market impact, currency and corporate-action
handling, benchmark alignment, performance reporting, and operational
reconciliation. No active-path integration is part of Phase E.

