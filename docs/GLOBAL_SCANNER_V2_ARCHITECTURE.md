# Global Scanner v2 Architecture

Global Scanner is a research-only producer. It must not import paper execution,
portfolio management, broker, tracker, authentication, deployment, or runtime
service code.

## Current State

`data/universes/*.csv` -> `research.global_scanner.load_universe` -> one
`yfinance.download` request -> ticker-by-ticker feature calculation -> scoring ->
direct ranking/candidate/history CSV writes -> dashboard CSV reads.

The current producer redownloads a full period, has no bounded batching or
per-symbol failure model, writes outputs independently, and uses output file
modification time instead of a scan manifest. The dashboard also starts a scan
inside Streamlit and reads universe files for presentation enrichment.

## Target Flow

Named universe files -> canonical universe and memberships -> structural
eligibility -> deterministic incremental batches -> canonical feature store ->
scoring -> atomic rankings/candidates/rejections/manifest/history -> dashboard.

The feature store is keyed by `(ticker, as_of_date)`. Scoring consumes only that
store. Dashboard code consumes only producer outputs and never downloads prices
or calculates indicators.

## Delivery Phases

1. Canonical universe, membership, rejection, batching, incremental-refresh,
   feature-key, ranking, manifest, and atomic-publication contracts.
2. Extend the existing market-data/cache path with bounded batches, retries,
   per-symbol errors, and incremental bar refresh. Do not add another price cache.
3. Move existing quality/risk/technical calculations into the canonical feature
   producer; preserve score semantics.
4. Publish complete scan generations, history, movement, rejection and coverage
   outputs; retain the last complete generation on critical failure.
5. Make the dashboard consume rankings, candidates, features and manifest only;
   remove in-process scans and universe-side calculations.

## First Reliable 500-Asset Milestone

The first milestone is deterministic safety, not a large live ticker list:

- canonical deduplicated assets with retained named-universe memberships;
- explicit pre-download and post-download rejection reasons;
- bounded deterministic batch plans and incremental refresh windows;
- unique ticker/as-of feature keys;
- deterministic global and per-universe ranking;
- reconciled coverage manifests;
- atomic CSV publication with the manifest as completion marker;
- fixture validation at 500 and 1,500 assets.

Full and intraday scanner commands will be exposed in Phase 2. They must remain
independent of the five-minute trading runtime.

## Phase 2: Canonical Scanner Bar Store

Scanner bars are stored as one deterministic CSV partition per ticker beneath
`data/global_scanner/bar_store/bars/`. CSV is used because the repository does
not currently declare a Parquet engine. Per-ticker partitions avoid rewriting a
universe-sized file for one incremental update, remain inspectable, and are
published through the existing atomic multi-file writer.

Each row is keyed by `(ticker, date)` and contains adjusted OHLCV, source,
fetch timestamp, and adjusted status. Incoming overlap is validated before the
latest fetched row replaces a cached row. Older history is retained. Conflicting
duplicates, malformed OHLC, invalid volume, empty responses, invalid timestamps,
insufficient history, and stale final bars have stable failure codes.

The acquisition flow is:

canonical universe -> serialisable deterministic plan -> bounded ticker batches
-> per-symbol validated results -> individual fallback retries -> atomic changed
partitions -> results/rejections -> acquisition manifest completion marker.

The default worker count is one. The configuration exposes a bounded worker
limit, but parallel yfinance execution is intentionally not enabled until its
cache/thread behaviour is proven safe. Scanner v2 uses a process-specific
yfinance timezone-cache directory and does not change trading market-data cache
behaviour.

Commands:

```text
python -m research.scanner_v2.acquire --universe core_existing --dry-run
python -m research.scanner_v2.acquire --universe sp500
python -m research.scanner_v2.acquire --all-enabled
```

Dry-run builds and prints the plan without downloads or canonical writes. Live
network smoke testing is optional and is not part of required validation.
