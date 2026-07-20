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

## Phase 3: Canonical Feature Production

The Phase 3 producer pins the active acquisition generation before reading any
partition. It processes one ticker at a time and publishes a separate immutable
feature generation. `current_generation.json` is replaced only after features,
rankings, candidates, rejections, movement and the manifest are complete. A
generation failure therefore leaves the previous pointer unchanged.

```text
python -m research.scanner_v2.features --generation current
python -m research.scanner_v2.features --dry-run
```

Dry-run reads the same pinned bar partitions and performs the full calculation,
ranking, comparison-completeness and reconciliation path, but writes nothing.
Partition-at-a-time reads bound bar memory; only one feature row per asset and
the ranking table are retained, so the layout remains suitable for 10,000+ assets.

### Migration map

| Legacy input/calculation | Canonical bar input | Feature/ranking field | Deferred dashboard consumer |
|---|---|---|---|
| Wide Close last value | ticker `close` partition | `latest_close`, `latest_price_date` | cards and tables |
| Wide-frame date/null alignment | ticker dates plus generation reference date | `missing_close_pct`, `stale_latest_price`, quality components | diagnostics |
| EMA20/50, RSI14, MACD and Volume20 flags | ticker close/volume | five flags, indicator values, `technical_score` | cards/comparison |
| Close × volume mean, trailing 60 | ticker close/volume | `avg_traded_value_60d`, liquidity/volume components | cards/comparison |
| Returns standard deviation | ticker close | `volatility_20d`, `volatility_60d` (%) | risk/comparison |
| True range mean, 14 bars | ticker OHLC | `atr_percent` (%) | risk/comparison |
| Close/running peak, trailing 252 | ticker close | `max_drawdown_1y` (%) | risk/comparison |
| Trend/swing/volatility/drawdown blend | canonical ticker features | `trend_stability_score` (0–100) | risk/comparison |
| Legacy six-component sum | canonical component fields | `scanner_score`, `global_score` (0–160) | rank and selection |
| Quality/score/liquidity/ticker sort | canonical features and memberships | `global_rank`, `universe_ranks` | ranking tables |
| Mutable prior snapshot inference | prior active feature ranking | movement state, rank/score deltas | movement/history |

`latest_rankings.csv` and `selected_candidates.csv` have identical schemas; the
latter is only the selected row subset. This removes the legacy schema drift
caused by selecting candidates before history and persistence enrichment.

### Feature dictionary

All nulls are explicit CSV nulls. Calculation exceptions produce a `failed` row;
quality-rule failures produce a `rejected` row; neither receives a hidden score.

| Field group | Source/formula and units | Minimum history / null and rejection handling |
|---|---|---|
| Price/freshness | final adjusted close and date; stale when older than generation reference by 7 calendar days; freshness 20 for price plus 20 if fresh | one bar; missing partition fails |
| History/missingness | bar count; absent business dates divided by expected business dates; history `min(count/252,1)×20`; completeness `(1-missing)×20` | 126 to score; >10% missing rejects |
| Technical indicators | EMA20/EMA50 price tests with existing ticker threshold; RSI14 in (45,70); MACD12/26 above EMA9 signal; volume above SMA20 | 60 bars; insufficient history rejects; no forward fill |
| Technical score | sum of five Boolean tests, 0–5; component `score×10` | 60 bars; null on insufficient history |
| Liquidity/volume | mean adjusted close × volume over 60 bars, native currency/day; component `min(log10(max(value,1))×2,20)`; recent volume component 0/10 | available observations; zero recent volume rejects |
| Volatility | sample standard deviation of daily returns over 20/60 observations ×√252×100, percent | two returns; null if insufficient |
| ATR | mean 14-bar true range/latest close×100, percent | available true ranges; null if unavailable |
| Max drawdown | absolute minimum of close/running maximum over final 252 bars×100, percent | one bar |
| Trend stability | above-EMA50 consistency 40 + low large-swing frequency 20 + inverse volatility 20 + inverse drawdown 20 | 60 bars; null if unavailable |
| Risk | capped vol/80×40 + drawdown/60×40 + ATR/8×20; labels at 20/40/60/80 | all three diagnostics; otherwise Unknown |
| Confidence | `(freshness + history + missingness + volume) / 90`, 0–1 | explicit zero for failed assets |
| Total score | freshness + history + missingness + volume + technical + liquidity, 0–160 | only quality-passing rows enter ranking |
| Metadata | canonical universe and membership join | preserved strings; memberships sorted and pipe-delimited |
| Terminal state | exactly one of scored/rejected/failed; rejection reasons sorted and pipe-delimited | no asset may occupy two states |

The intentional differences from the legacy wide frame are: technical inputs are
never forward-filled; missingness is measured from each partition's business-date
coverage rather than another asset's index; drawdown is explicitly capped to 252
observations; missing OHLC never falls back to a close-only ATR approximation; and
download/feature failures are distinct from quality rejection. Complete-bar golden
fixtures preserve legacy indicators, weights, thresholds, score and tie-breaking.

Dry-run builds and prints the plan without downloads or canonical writes. Live
network smoke testing is optional and is not part of required validation.

## Phase 4: Read-Only Dashboard Consumer

The dashboard consumes only the active immutable feature generation through
`dashboard/scanner_reader.py`. The reader resolves
`data/global_scanner/feature_store/current_generation.json`, requires the pointer
to reference an existing generation, and validates the completion manifest before
returning any data.

The active generation layout is:

```text
data/global_scanner/feature_store/
  current_generation.json
  generations/<generation_id>/
    scanner_features.csv
    latest_rankings.csv
    selected_candidates.csv
    rejected_assets.csv
    ranking_movement.csv
    scanner_generation_manifest.json
```

The reader verifies pointer/manifest identity, `status == "complete"`, all five
CSV artifacts, their manifest-declared SHA-256 hashes, required columns, feature
terminal-state reconciliation, and manifest row counts. Missing pointers,
missing generations or artifacts, malformed manifests, incomplete generations,
hash failures, schema failures, and valid empty candidate sets remain distinct
consumer states. Validation failures are visible in the UI and are never
converted silently into empty frames.

The dashboard may format, filter, sort, paginate, aggregate displayed rows, and
reload the already-published pointer from disk. It must not download market data,
invoke a scanner, calculate indicators or scores, rank or select assets, infer
movement, read raw universe files, use file modification time as scanner
freshness, repair artifacts, or write scanner state. Portfolio-fit calculations
were removed from the scanner presentation until an equivalent result is
published by an upstream canonical producer.

Produce data outside Streamlit:

```text
python -m research.scanner_v2.acquire --all-enabled
python -m research.scanner_v2.features --generation current
```

The dashboard's **Reload published generation** button only rereads the active
immutable generation. Phase 4 removed the legacy flat-file reads, history-folder
reconstruction, automatic stale-output scan, manual producer button, legacy
`research.global_scanner` import, and raw-universe enrichment from the dashboard.

## Phase 5: Canonical Investment Intelligence

Scanner v2 owns deterministic asset and portfolio-context intelligence. The
dashboard owns formatting and rendering; Research Lab, Strategy Engine, APIs and
other consumers read the same immutable artifacts. Consumers must not reproduce
Scanner labels, percentiles, peer ranks or portfolio-fit rules.

### Generation bundle

`research.scanner_v2.generation.ScannerGeneration` treats publication as one
bundle rather than unrelated files:

```text
Generation
  Manifest and metadata
  scanner_features.csv
  latest_rankings.csv
  selected_candidates.csv
  rejected_assets.csv
  ranking_movement.csv
  portfolio_fit.csv
```

All six CSVs are staged beneath one generation directory, included in the
manifest hash map, validated as one contract, and made visible by the existing
single pointer swap. Existing manifest fields and count semantics are unchanged.
Additive fields are `intelligence_schema_version` and `portfolio_fit_assets`.
The scoring version remains `legacy-scanner-score-v1`; Phase 5 does not change
the scanner score, sort keys, candidate cutoff, persistence or movement rules.

### Canonical intelligence schema

The feature schema is additive and versioned as `scanner-features-v2` with
`scanner-intelligence-v1` intelligence semantics.

| Group | Published fields | Deterministic rule |
|---|---|---|
| Returns | `return_20d_pct`, `return_60d_pct`, `return_252d_pct` | Point-to-point adjusted-close returns when sufficient bars exist |
| Price range | `high_52w`, `low_52w`, `percentile_52w`, distances from high/low | Final 252 observations; breakout compares latest close with the prior window |
| Trend | EMA distances, `moving_average_alignment`, `trend_regime`, `trend_strength_pct`, bullish/bearish flags | Bullish when close > EMA20 > EMA50; bearish for the inverse; otherwise mixed |
| Momentum | `momentum_regime` | 20-day return: high at >=10%, positive above 0%, low at <=-10%, otherwise negative |
| Breakout/mean reversion | `breakout_state`, `mean_reversion_state` | Prior 52-week bounds; EMA20 extension at +/-5% |
| Volatility | `volatility_regime`, `rolling_volatility_percentile`, `atr_percentile` | Stable below 20%, moderate below 45%, otherwise volatile; percentiles among scored assets |
| Liquidity | average volume, volume percentile, native traded value, currency, liquidity percentile/bucket, tradability | Traded-value percentiles are within listing currency; high >=75th percentile, medium >=25th, otherwise low |
| Quality | `quality_bucket` | Confidence >=0.85 high, >=0.65 medium, otherwise low |
| Relative strength | `relative_strength_percentile` | Cross-sectional percentile of 60-day return among scored assets |
| Peer intelligence | sector/country ranks and percentiles, sector candidate rank/count, sector average score | Stable global score/liquidity/ticker order within canonical metadata groups |

`average_daily_traded_value_60d` is in the asset's listing currency and
`traded_value_currency` identifies that unit. `average_dollar_volume_60d` and
`spread_estimate` remain null because Scanner v2 has neither canonical FX rates
nor bid/ask data. Growth/defensive labels are not published because the current
inputs do not support them without fabrication. Country intelligence is available
from canonical universe metadata; missing values form an explicit `Unknown` group.

### Portfolio intelligence producer

`research/scanner_v2/portfolio_intelligence.py` consumes published candidates,
canonical feature metadata, and an optional valued holdings snapshot. It emits
one `portfolio_fit.csv` row per candidate with held status, sector/country/
currency/asset-type overlap percentages, concentration impact, a bounded
diversification score, status and explanation text. The deterministic rules are
the former dashboard rules, now centralized upstream.

If holdings are absent, malformed, or have no positive market value, every
candidate receives `portfolio_fit_status=unavailable`, null overlap/score fields,
and an explanation. The producer never reads raw universe files and never invents
portfolio context. Supply an optional snapshot explicitly:

```text
python -m research.scanner_v2.features --generation current --holdings holdings_report.csv
```

Research and strategy consumers may immediately read the generation CSVs or use
the validated bundle contract. The Phase 5 intelligence and generation modules
import no dashboard, runtime, accounting, ledger, Supabase or deployment code.

## Phase 6: Scanner Generation Research

Research is a one-way, read-only consumer of completed `ScannerGeneration`
bundles. Scanner never imports Research; Dashboard and Execution do not calculate
research results. The Phase 6 backend deliberately has no dashboard, execution,
runtime, accounting, Streamlit, yfinance, or network dependency.

```text
ScannerGeneration history
  -> ScannerResearchReader
  -> historical_dataset.csv
  -> pinned forward-return outcomes
  -> deterministic analytics
  -> immutable research report generation
```

`research/scanner_generation_reader.py` loads the active generation, explicit
generation IDs, the complete generation history, or an inclusive manifest-time
range. Every load validates completion, identity, the six canonical artifact
hashes, counts, and the `ScannerGeneration` schema. A malformed historical
generation is reported rather than silently skipped.

`research/scanner_history.py` creates one observation per
`generation_id`/`ticker`/`as_of_date`. It joins only fields already published in
features, rankings, movement, candidate membership, persistence, and portfolio
fit; it does not reconstruct Scanner intelligence. Manifest counts and source
generation metadata remain attached to each observation.

`research/scanner_forward_returns.py` adds 5, 20, 60, 120 and 252-observation
forward returns from an explicitly pinned immutable bar generation. The base is
the first canonical close on or after the feature `as_of_date`; the target is
exactly N later observations. Missing future history stays null. Features are
never backfilled or recalculated, preventing outcome data from leaking into the
point-in-time feature record.

The analytics layer reports return distributions by rank decile, sector,
country, liquidity and quality bucket, volatility/trend/momentum regime,
persistence bucket, and published candidate status. Metrics are observation and
outcome counts, mean/median return, hit/win/loss rates, average gain/loss,
annualized Sharpe and maximum drawdown. Maximum drawdown is the drawdown of the
cumulative return path in deterministic observation order; it is a grouped
research diagnostic, not a simulated portfolio equity curve.

Numeric factors use Spearman rank correlation with forward return. Categorical
factors use eta-squared across their published groups. Both are descriptive,
deterministic statistics; Phase 6 introduces no machine learning, optimized
weights, trading rules, or feedback into Scanner ranking.

Each report run is an immutable directory and refuses overwrite:

```text
research_reports/generations/<report_id>/
  historical_dataset.csv
  factor_report.csv
  sector_report.csv
  country_report.csv
  bucket_report.csv
  regime_report.csv
  candidate_report.csv
  ranking_report.csv
  research_summary.json
  research_manifest.json
```

The research manifest pins all source Scanner generation IDs and the outcome bar
generation, records table counts, and declares SHA-256 hashes for every report
artifact. Reports may be built through
`research.scanner_research_reports.run_scanner_research`; callers supply isolated
feature-store, bar-store and report roots plus optional generation IDs or date
bounds. Report publication writes only to the supplied research-report root and
never changes Scanner artifacts or pointers.
