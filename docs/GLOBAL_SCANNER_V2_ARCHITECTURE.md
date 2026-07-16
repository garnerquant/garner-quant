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
