# Continuous Research Improvement

The continuous research loop is advisory. It observes immutable evidence, produces traceable research artifacts, and stops before experiment execution or any strategy change.

```text
Trade → Evidence → Observation → Hypothesis → Experiment → Validation
      → Proposal → Human approval → Shadow → Deployment review → Trade
```

## Initial lifecycle

The first implementation covers evidence snapshots, observations, a controlled feature catalogue, deterministic grouped analyses, ranked hypotheses, proposed research tasks, and immutable morning reports. Experiment specifications are described by hypotheses and tasks but are not executed. Strategy proposals, approvals, shadow evaluation, and deployment are future phases.

An observation describes an association in recorded evidence. It is not a hypothesis, recommendation, validation, or strategy change. A hypothesis is falsifiable and proposes a controlled experiment. Tasks remain `PROPOSED`; manual approval is mandatory before any future experiment.

## Evidence and provenance

The snapshot reads completed trade audit rows, ledger events, and monitor-only decision traces through an explicit field allowlist. Every datum carries its source artifact, row identity, source version, timestamps, schema, status, and hash. The snapshot records source file hashes and a fixed cut-off. Records after the cut-off are excluded.

Unavailable MFE/MAE, slippage, strategy versions, entry-time regimes, breadth, portfolio context, and rejected-signal counterfactual outcomes remain unavailable. They are never inferred.

## Features and analysis

The feature catalogue defines source fields, missing-value policy, calculation version, look-ahead rule, leakage risk, and minimum evidence. The initial ten-analysis catalogue covers strategy, holding period, stop/target exits, weekday, and temporal comparisons when supported. Market/volatility regimes, agreement counts, and rejected-signal outcomes report explicit limitations until valid evidence exists.

Grouped comparisons report counts, means, medians, effect size, approximate raw significance, Benjamini–Hochberg adjusted significance, attempted comparison count, breadth warnings, and limitations. Minimum group samples are enforced. Labels remain exploratory or moderate, never guarantees. The analysis uses outcome information only as an outcome.

## Priority and uncertainty

Priority is a transparent sum of evidence quality, sample size, instrument breadth, leakage safety, and research cost. It is not based solely on observed uplift. Duplicate titles are flagged against prior hypotheses. Reports may correctly state that no robust new hypotheses were found; quotas are never filled with weak ideas.

## Morning report

A report includes an executive summary, trade/signal/strategy counts, up to five observations, three hypotheses, three proposed tasks, and three important limitations. Its identity and hash bind the evidence snapshot, fixed cut-off, creation time, and predecessor. Publication is immutable and refuses overwrite.

Run manually:

```powershell
python scripts/run_continuous_research.py --cutoff 2026-07-22T20:00:00+00:00 --created-at 2026-07-22T20:05:00+00:00
```

No scheduler is installed by this implementation.

## Human approval boundary

Research modules import no execution, runtime, strategy, risk, broker, or accounting packages. They cannot submit orders, alter active parameters, change risk limits, write portfolio state, or move accounting pointers. Future experiments require a frozen specification, untouched validation data, cost assumptions, robustness checks, and explicit approval. Validation and proposals must remain separate from experiment execution. A deployment requires separate human review, shadow observation, and activation decisions.

## Model usage

This version uses no language model. All numerical statements are deterministic. A future narrative model may summarize validated artifacts but may not invent numbers, approve findings, or modify measured results; model, prompt, input hashes, output hash, and timestamp would be required.

## Operator and recovery procedure

Review the evidence cut-off and limitations before reading hypotheses. Treat every finding as exploratory until a separately approved out-of-sample experiment is validated. To recover, retain all published report directories, verify their manifest and content hashes, and restore them without regeneration. Never delete rejected or inconclusive research history.
