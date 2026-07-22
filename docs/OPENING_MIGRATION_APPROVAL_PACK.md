# Opening Migration Allocation and Approval Pack

This is a read-only governance artifact derived exclusively from the existing Opening Snapshot Evidence Pack and Gap Register. It does not re-audit sources, create migration lots, construct an opening snapshot candidate, publish a generation, or create/move a pointer. No proposal changes accounting.

Each immutable proposal addresses one review issue, links an existing gap ID, records affected positions/cash/source-lot references and currency, states evidence and limitations, recommends an evidence-gathering action, and carries a deterministic materiality assessment. Strategy outcomes are `PROVEN`, `MANUAL_REQUIRED`, or `UNRESOLVED`; absent authoritative evidence leaves strategy null. Acquisition FX is never inferred. Opening-lot entries describe a possible future migration review only and are not lots.

The supported proposal types are strategy allocation, opening lot, opening cash, acquisition FX, dividend history, fee history, tax history, withholding, corporate action, and unknown. Deposit and withdrawal completeness are separate opening-cash reviews. Unsupported or unquantifiable history remains explicit rather than being assigned a value.

Materiality is based on the evidenced value affected as a percentage of observed portfolio exposure plus cash: low below 2%, medium from 2%, high from 10%, and critical from 25%. Unknown affected P&L is documented and never fabricated.

The immutable Approval Pack binds the repository commit, evidence hash, proposal hashes, coverage, and blockers. Approval records bind both pack and proposal hashes and support `PENDING`, `APPROVED`, `REJECTED`, and `CHANGES_REQUIRED`. A changed pack invalidates an old binding. Approval has no execution or accounting side effect and cannot make the pack activation-ready.

Operators must obtain authoritative evidence, review each proposal independently, and use a future separately controlled candidate workflow only after gaps are resolved. Canonical accounting remains **INACTIVE**. Paper and live execution remain disabled.
