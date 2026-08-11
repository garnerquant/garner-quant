# Manual shadow runbook

## 1. DOCUMENT STATUS

Document version: `1.0`
Reviewed HEAD: `fcc1754c653676621d90edb656407fee4abef7a5`
Classification: `shadow_observation_unverified`

This runbook describes a manual and offline research-only workflow. It is not
investment advice and is not approved for production capital.

## 2. PURPOSE

The manual shadow CLI accepts one explicitly supplied input document, strictly
decodes it through `decode_shadow_input(raw)`, constructs the existing
immutable `ShadowRunRequest`, runs the non-authoritative
`run_shadow_comparison(request)`, and prints a bounded deterministic JSON
summary.

The default invocation writes nothing. An immutable evidence copy is exported
only when an operator explicitly requests export mode and supplies every
required export argument. The CLI does not connect to runtime, scheduling,
dashboards, providers, brokers, notifications, accounting, or risk
authorization.

## 3. PREREQUISITES

- A repository checkout at the intended commit.
- The existing Python environment for the repository.
- The development requirements already declared by the project.
- One explicit manual shadow input JSON document.
- No provider credentials, broker credentials, runtime service, scheduler,
  dashboard, or external network access.
- For export mode only, an explicit output root that already exists, is outside
  the repository, is not a symbolic link, and is controlled by the operator.

Do not install undeclared packages for this workflow.

## 4. SAFETY MODEL

`research.shadow_runner.RESULT_CLASSIFICATION` is
`shadow_observation_unverified`. Every `ShadowRunResult` fixes these fields:

- `result_classification="shadow_observation_unverified"`
- `execution_authorized=false`
- `publication_authorized=false`
- `runtime_effect=false`
- `paper_effect=false`
- `accounting_effect=false`

Input documents cannot override these fields. Explicit evidence export records
an operator-requested copy of a non-authoritative result; it does not change
`publication_authorized` and does not grant authority to publish, trade, update
paper state, or affect production decisions.

## 5. INPUT SCHEMA

The decoder in `research.shadow_input` accepts only caller-supplied UTF-8 bytes
or text. Its public API is:

- `decode_shadow_input(raw)`
- `to_canonical_input_payload(decoded)`
- `to_canonical_input_bytes(decoded)`
- `canonical_input_sha256(decoded)`
- `raw_input_sha256(raw)`
- `DecodedShadowInput`
- `ShadowInputError`

Implemented constants:

- `SCHEMA_VERSION=1`
- `REQUEST_TYPE="manual_shadow_input_v1"`
- `MAX_INPUT_BYTES=262144`
- `MAX_DECISIONS=100`
- `MAX_LEGACY_OBSERVATIONS=200`
- `MAX_STRING_LENGTH=4096`
- `MAX_WARNINGS=32`
- `MAX_LIMITATIONS=32`
- `MAX_COLLECTION_LENGTH=256`

Top-level required fields:

- `schema_version`
- `request_type`
- `shadow_run_id`
- `created_at`
- `information_cutoff`
- `strategy_id`
- `strategy_version`
- `parameter_set_id`
- `code_version`
- `validated_evidence_identity`
- `validated_decisions`
- `legacy_observation_set_identity`
- `legacy_observations`
- `comparison_policy`
- `warnings`
- `limitations`

Each `validated_decisions` entry must contain:

- `decision_id`
- `strategy_id`
- `strategy_version`
- `instrument_id`
- `decision_timestamp_utc`
- `information_cutoff_utc`
- `eligible_execution_timestamp_utc`
- `decision_action`
- `decision_status`
- `signal_value`
- `target_weight`
- `currency`
- `price_unit`
- `quality_status`
- `reason_codes`
- `dataset_version`
- `universe_version`
- `parameter_version`
- `code_revision`

`legacy_observations`, when present, must contain `schema_version`, `signals`,
`weights`, `projections`, `methodology_classification`, and `limitations`.
Signal, weight, and projection observations use the exact field names enforced
by `research.shadow_input`; missing quantitative values remain `null`, not
zero.

`comparison_policy` must contain `schema_version`, `policy_id`,
`policy_version`, `base_currency`, `validated_methodology`, and
`legacy_methodology`. The runner currently supports policy
`("shadow", "1")`.

Timestamp fields must use canonical UTC form:
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Date fields use `YYYY-MM-DD`. Naive timestamps,
non-UTC offsets, malformed dates, and future evidence after
`information_cutoff` fail closed.

Decimal values must be canonical strings. JSON floats, `NaN`, infinity,
scientific notation, malformed decimals, and noncanonical decimal spellings are
rejected. Negative zero is normalized consistently to canonical zero in decoded
content.

The decoder rejects malformed JSON, invalid UTF-8, UTF-8 BOM input, duplicate
keys at any object level, unknown fields, missing required fields, unknown
schema or request versions, invalid enum/status values, duplicate or
conflicting decision identities, duplicate or conflicting legacy identities,
identity/hash mismatches, embedded filesystem paths, shell syntax, URLs, and
attempts to include fixed safety fields.

Raw input SHA-256 identifies the supplied document bytes. Canonical input
SHA-256 identifies the decoded semantic content. Different JSON key ordering
may change the raw hash but must not change the canonical hash; meaningful
value changes must change the canonical hash. Hashes are lowercase SHA-256
without salt, environment state, or filesystem state.

## 6. PREPARING INPUT

The following structural example is synthetic placeholder data only. It is not
a production input and the placeholder hashes must be replaced with hashes
computed from the exact decoded content before use.

```json
{
  "schema_version": 1,
  "request_type": "manual_shadow_input_v1",
  "shadow_run_id": "shadow-example-001",
  "created_at": "2025-01-02T16:00:00.000000Z",
  "information_cutoff": "2025-01-02T16:00:00.000000Z",
  "strategy_id": "shadow-strategy",
  "strategy_version": "1",
  "parameter_set_id": "parameters",
  "code_version": "code",
  "validated_evidence_identity": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "validated_decisions": [
    {
      "decision_id": "decision-SYNTH",
      "strategy_id": "shadow-strategy",
      "strategy_version": "1",
      "instrument_id": "SYNTH",
      "decision_timestamp_utc": "2025-01-02T16:00:00.000000Z",
      "information_cutoff_utc": "2025-01-02T16:00:00.000000Z",
      "eligible_execution_timestamp_utc": "2025-01-02T16:00:00.000000Z",
      "decision_action": "buy",
      "decision_status": "eligible",
      "signal_value": "1",
      "target_weight": "0.1",
      "currency": "GBP",
      "price_unit": "GBP",
      "quality_status": "valid",
      "reason_codes": [],
      "dataset_version": "dataset",
      "universe_version": "universe",
      "parameter_version": "parameters",
      "code_revision": "code"
    }
  ],
  "legacy_observation_set_identity": null,
  "legacy_observations": null,
  "comparison_policy": {
    "schema_version": 1,
    "policy_id": "shadow",
    "policy_version": "1",
    "base_currency": "GBP",
    "validated_methodology": "technical_only_historical_v1",
    "legacy_methodology": "legacy_current_fundamental_unverified"
  },
  "warnings": [],
  "limitations": []
}
```

Adapt the example through the documented schema and validate it before use.
Do not include credentials, real holdings, tokens, private hostnames, or
production identifiers in manual shadow input.

## 7. CLI

The CLI module is `scripts/run_shadow_research.py`. Its public testable API is
`build_parser()` and `main(argv=None, stdout=None, stderr=None)`. Importing the
module must not execute the CLI.

Default no-export invocation:

```powershell
.\venv\Scripts\python.exe scripts\run_shadow_research.py `
  --input <explicit-input-json>
```

Explicit export invocation:

```powershell
.\venv\Scripts\python.exe scripts\run_shadow_research.py `
  --input <explicit-input-json> `
  --export `
  --output-root <external-output-root> `
  --export-id <safe-export-id> `
  --export-created-at <YYYY-MM-DDTHH:MM:SS.ffffffZ> `
  --operator-purpose <operator-purpose>
```

There are no default input paths, no default output paths, no implicit
timestamp, and no generated export ID. Supplying any export option without
`--export` fails. Supplying `--export` without all export options fails.

## 8. INPUT FILE HANDLING

The CLI reads only the file named by `--input`. Before reading it requires an
existing regular file, rejects directories, rejects symbolic-link or
reparse-like input where detectable, rejects oversized files before decoding,
does not scan parent directories, and reads exact binary bytes. The raw bytes
are passed directly to `decode_shadow_input(raw)` without repair or
normalization.

An explicit valid input outside the repository is allowed. Normal output does
not expose complete absolute paths.

## 9. SUMMARY OUTPUT

Successful runs print sorted compact JSON and one terminal newline. The
summary is bounded to identities and counts:

- schema and request type
- `shadow_run_id`
- `raw_input_sha256`
- `canonical_input_sha256`
- `shadow_result_sha256`
- `result_classification`
- compared instrument count
- outcome counts
- unavailable or rejected count
- fixed false safety fields
- export requested and verified flags
- `export_id` only when export mode is used

The summary does not print raw input, complete decisions, complete legacy
observations, credentials, environment values, stack traces, or full successful
export paths.

## 10. EXPORT AND VERIFICATION

Export mode delegates to `export_shadow_report(...)` and then
`verify_shadow_report(...)`. The exporter also exposes
`build_export_metadata(...)` and `canonical_export_sha256(...)`.

Required export inputs are:

- `ShadowRunResult`
- explicit `output_root`
- `export_id`
- UTC-aware `created_at`
- `operator_purpose`
- `code_version`
- `raw_input_sha256`
- `canonical_input_sha256`

The exporter writes exactly one namespace:
`<explicit_output_root>/<export_id>/`. It rejects the repository root,
repository subdirectories, symbolic-link roots or namespace components where
detectable, traversal, unsafe export IDs, conflicting exports, and existing
unexpected content.

Successful export contains exactly:

- `shadow_result.json`
- `export_metadata.json`
- `content_manifest.json`

The verifier fails closed unless the namespace is a real non-link directory,
membership is exactly the three files above, files are regular non-links,
manifest JSON is valid, filenames are safe flat relative names, sizes and
SHA-256 values match, result and metadata identities match, input hashes are
valid, classification remains `shadow_observation_unverified`, and all fixed
safety fields remain false.

Byte-identical repeat export is idempotent. Conflicting repeat export fails
and is not overwritten.

## 11. EXIT CODES

The CLI uses these stable exit-code constants and values:

- `EXIT_OK=0`: success, with or without verified export
- `EXIT_ARGUMENTS=2`: invalid CLI arguments
- `EXIT_INPUT=3`: input path or read failure
- `EXIT_DECODING=4`: input decoding or validation failure
- `EXIT_RUNNER=5`: shadow runner failure
- `EXIT_EXPORT=6`: export failure
- `EXIT_VERIFICATION=7`: export verification failure

Ordinary failures print bounded sanitized JSON to stderr with `category`,
`exit_code`, and `reason`. They do not print stack traces or raw input.

## 12. OPERATIONAL BOUNDARIES

This manual CLI has no API for order submission, paper portfolio update, risk
authorization, ledger or accounting commit, notifications, Supabase writes,
filesystem publication outside explicit export mode, scheduler registration,
dashboard mutation, runtime control, provider access, broker access, or
workflow dispatch.

It is not imported by active production modules and does not modify application
entry points.

## 13. TEST EVIDENCE

Recorded TKT-041 focused result:

`76 passed`

Recorded TKT-041 approved result:

`219 passed, 1 skipped, 32 subtests passed`

Recorded TKT-042 focused result:

`87 passed, 1 skipped`

Recorded TKT-042 approved result:

`243 passed, 2 skipped, 32 subtests passed`

Recorded TKT-043 focused result:

`107 passed, 2 skipped`

Recorded TKT-043 approved result:

`263 passed, 3 skipped, 32 subtests passed`

These records are focused and approved-suite evidence for Phase G work. They
are not a broad legacy-suite claim.

The baseline manifest SHA-256 is
`E634DCFEB8AFE5A847CA29C529C19BD88AC2B9711B7161694EC4D1CA36CF89D8`.
It inventories 47 artifacts, including 30 immutable evidence artifacts and 17
mutable runtime-state artifacts.

## 14. PHASE G CHECKPOINT COMMITS

The completed Phase G commits before this document commit are:

1. SHA `f17c769a4d89c743d6a9dcef9f8fecd71d9a1b27`; parent
   `bd9dec1cd6e37994a593d24dd5d637c03413205d`; message
   `feat: add strict manual shadow input decoding`; files
   `research/shadow_input.py` and `tests/test_shadow_input.py`.
2. SHA `2454013004b31735e0dace3a776a2d1aa7b7892b`; parent
   `f17c769a4d89c743d6a9dcef9f8fecd71d9a1b27`; message
   `feat: add immutable shadow report export`; files
   `research/shadow_report.py` and `tests/test_shadow_report.py`.
3. SHA `fcc1754c653676621d90edb656407fee4abef7a5`; parent
   `2454013004b31735e0dace3a776a2d1aa7b7892b`; message
   `feat: add manual offline shadow CLI`; files
   `scripts/run_shadow_research.py` and `tests/test_shadow_cli.py`.
4. This document commit; parent
   `fcc1754c653676621d90edb656407fee4abef7a5`; message
   `docs: add manual shadow runbook`; file
   `docs/manual_shadow_runbook.md`.

This document is not amended to insert its own final SHA.

## 15. DEPLOYMENT SAFETY

Automatic push deployment is disabled. Deployment requires
`workflow_dispatch`. Phase G has not been pushed and no deployment has
occurred at this local checkpoint.

The deployment workflow remains manual-only. This runbook does not instruct an
operator to push, deploy, trigger workflow dispatch, start services, or
schedule shadow runs.

## 16. LIMITATIONS AND NEXT GATES

The manual shadow workflow does not acquire market data automatically, does
not provide a historical point-in-time fundamental dataset, does not run on a
schedule, does not persist remotely, has no dashboard presentation, performs no
broker comparison, and does not establish performance, execution realism,
backtest parity, paper parity, production readiness, or production-capital
approval.

Before shadow results may influence trading, a separate explicit phase must
cover independent validation, broker sandbox behavior, order lifecycle,
partial fills and rejection handling, accounting reconciliation, approved risk
limits, kill-switch integration, deployment controls, and owner authorization.
