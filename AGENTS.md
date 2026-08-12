# Garner Quant Operating Rules

## 1. Project purpose and architecture

Garner Quant is a Python research and paper-trading project for systematic strategy development, validation, monitoring, and auditability.

- `dashboard-web/` is a standalone Next.js dashboard preview.
- `dashboard-api/` is an isolated, read-only API for dashboard data.
- The existing Streamlit/Python dashboard remains a separate system and must not be conflated with the standalone dashboard.

## 2. Working principles

- Inspect the repository, current changes, and relevant contracts before editing.
- Preserve existing user changes; do not overwrite or normalise unrelated work.
- Use small, reversible, ticket-scoped changes.
- Make assumptions explicit when the task does not specify a detail.
- Prefer deterministic, testable implementations with clear failure behaviour.

## 3. Scope control

- Follow the authorised file allowlist for each ticket.
- Stop and request direction if implementation requires files outside the allowlist.
- Do not modify unrelated production modules.
- Do not silently broaden the task or add adjacent integrations.

## 4. Finance safety rules

Preserve these safety defaults:

- `mode=monitor_only`
- `paper_execution_enabled=false`
- `trading_enabled=false`
- `limits_approved=false`

Never enable trading or paper execution. Never place, submit, cancel, or modify orders. Never connect brokers, providers, external services, notifications, or schedulers unless explicitly authorised. Never modify risk limits or runtime safety defaults without explicit approval.

## 5. Data integrity rules

- Verify the baseline manifest before and after changes.
- Immutable artifacts must not change unexpectedly.
- Classify mutable runtime drift separately from immutable-artifact results.
- Do not restore, overwrite, or silently normalise mutable runtime files.
- Never mix data from different timestamps without an explicit contract.
- Fail closed on stale, incomplete, malformed, duplicate, or inconsistent evidence.
- Distinguish generated time from source/as-of time.
- Never present mock data as real data.

## 6. Dashboard rules

- Treat dashboards as preview/read-only unless explicitly authorised otherwise.
- Preserve clear source classifications such as `local_snapshot`, `partial`, `stale`, `unavailable`, and `mock_preview`.
- Do not permit browser-to-provider access.
- API endpoints must be explicitly typed and read-only.
- All repository mounts into containers must be explicit and read-only.
- Preserve the manual-only deployment workflow.

## 7. Coding and testing rules

- Use existing project conventions.
- Use `apply_patch` for edits where applicable.
- Run focused tests first, then the approved wider suite.
- Run AST/import/capability audits for new services.
- Run `git diff --check`.
- Run `pip check` where relevant.
- For dashboard work, run TypeScript, ESLint, Next.js production build, and Docker Compose checks.
- Do not treat unrelated environment failures as application failures.
- Report skipped tests and environmental limitations clearly.

## 8. Git rules

- Never use destructive commands without explicit authorisation.
- Never rewrite history.
- Never force-push.
- Do not push unless explicitly requested.
- Do not merge pull requests unless explicitly requested.
- Create small, descriptive commits.
- Inspect staged files before committing.
- Ensure the worktree is clean after a checkpoint.

## 9. Autonomous-work rules

- Codex may work autonomously within the authorised ticket scope.
- Codex may create branches, implement changes, run checks, and open pull requests when authorised by the task.
- Codex must stop on failed gates, unexpected drift, scope expansion, missing authority, or safety ambiguity.
- Codex must not merge, deploy, enable trading, or change risk controls autonomously.
- Every final report must include changed files, tests, integrity status, safety status, and remaining limitations.

## 10. Required final report

Every completed task report must state:

- Ticket or task name.
- Starting and ending commit.
- Files changed.
- Tests and checks run.
- Immutable artifact result.
- Mutable drift result.
- Safety-default result.
- Deployment and push status.
- Limitations and deferred work.
