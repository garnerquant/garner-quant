# Garner Quant Dashboard Work Plan

This plan covers the remaining standalone dashboard work. It preserves the existing split between the Python research and paper-trading system, the isolated read-only `dashboard-api/`, the standalone Next.js preview in `dashboard-web/`, and the separate Streamlit/Python dashboard.

## Phase 1 — Completed

Completed foundations:

- Standalone Next.js dashboard preview — `363b866f`.
- Docker Compose dashboard preview.
- Read-only dashboard API.
- Overview API integration — `838640a6`.
- Portfolio API integration — `0660a6a`.
- Strict stale, partial, and unavailable data handling.
- `AGENTS.md` repository operating rules — `1572393`.

These completed capabilities remain preview/read-only. They do not authorise trading, runtime mutation, provider access, or automatic deployment.

## Phase 2 — Signals integration

Connect only the Signals page to a read-only API.

- Inspect `signal_report_v2.csv` and its schema and provenance.
- Define the source timestamp and freshness policy before implementation.
- Expose only trustworthy rows.
- Preserve `local_snapshot`, `partial`, `stale`, and `unavailable` classifications as applicable.
- Do not mix mock and API fields in one displayed result.
- Use a same-origin Next.js proxy.
- Expose a GET-only endpoint with an explicit response contract.
- Add focused API and frontend integration tests.
- Add no execution or trading capability.

## Phase 3 — Markets integration

Connect only the Markets page.

- Inspect available market-data snapshots and their provenance.
- Preserve price-unit and currency metadata.
- Distinguish completed bars, stale data, and unavailable data.
- Make no provider calls from the dashboard.
- Do not invent FX conversion or benchmark values.
- Use a read-only GET endpoint.
- Maintain the existing candlestick preview where validated data is unavailable.
- Add focused tests and reconciliation checks.

## Phase 4 — Research integration

Connect only the Research page.

- Expose only reproducible, validated research-run evidence.
- Preserve dataset, universe, parameter, strategy, execution-model, cost-model, information-cutoff, and code versions when available.
- Distinguish exploratory, unverified, and validated results.
- Expose benchmark data only when currency conversion is evidenced.
- Make no performance claims beyond the available evidence.
- Use a GET-only endpoint with a versioned response contract.
- Add focused API and frontend tests.

## Phase 5 — Shadow Runs integration

Connect only the Shadow Runs page.

- Preserve the manual input boundary.
- Preserve the strict decoder and runner contracts.
- Expose comparison results read-only.
- Do not provide browser-side filesystem access.
- Do not export results unless export is explicitly controlled and separately authorised.
- Preserve the absence of execution and runtime effects.
- Add focused API and frontend tests.

## Phase 6 — Risk & Health integration

Connect only read-only health and safety status.

- Expose current monitor-only state.
- Expose heartbeat and data-quality status.
- Never expose mutation controls.
- Never change risk controls from the dashboard.
- Fail closed when status evidence is missing or stale.
- Use a GET-only API with focused tests.

## Phase 7 — Audit integration

Connect only the Audit page.

- Expose artifact classifications, hashes, timestamps, and verification status.
- Distinguish immutable evidence from mutable runtime state.
- Never modify or repair artifacts.
- Preserve sensitive-data redaction.
- Use a GET-only endpoint.
- Provide deterministic ordering and focused tests.

## Phase 8 — End-to-end validation

Before considering the dashboard work complete, run and record:

- API contract tests.
- Frontend integration tests for all eight routes.
- TypeScript, ESLint, and the Next.js production build.
- Python `pip check`.
- Docker Compose validation.
- Container health checks.
- API, proxy, and page route health checks.
- Immutable manifest verification.
- Mutable runtime drift reporting.
- Import, AST, and capability audits for new services.
- No-mock/API-mixing checks.
- Confirmation that no production runtime files changed.
- Confirmation that no deployment occurs until explicitly approved.

## Operating sequence

Each phase must follow this sequence and stop before the next phase:

1. Inspect sources and schemas.
2. Document the source-to-field mapping.
3. Implement one endpoint and one page only.
4. Add focused tests.
5. Run validation.
6. Show the local preview.
7. Wait for visual approval.
8. Create a local checkpoint commit.
9. Push only when explicitly requested.
10. Stop before the next phase.

## Explicit non-goals

This plan does not authorise:

- Trading.
- Order entry.
- Broker integration.
- Provider integration.
- Automatic deployment.
- Runtime mutation.
- Accounting writes.
- Notifications.
- Scheduler changes.
- Live capital.
- Performance claims.
- Removal of the existing Streamlit/Python dashboard.

## Definition of done

A phase is complete only when:

- Source provenance is explicit.
- Stale and partial data are visible.
- Unavailable values are not fabricated.
- API and frontend tests pass.
- Safety defaults remain unchanged.
- Immutable artifacts are intact.
- The dashboard preview is visually reviewed.
- The checkpoint commit is clean.
- No unapproved production integration exists.
