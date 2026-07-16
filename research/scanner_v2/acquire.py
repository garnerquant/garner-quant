from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from research.scanner_v2.acquisition import AcquisitionConfig, YFinanceDownloader, acquire_plan, acquisition_manifest, build_acquisition_plan, configure_scanner_yfinance_cache
from research.scanner_v2.bar_store import ScannerBarStore, merge_bars
from research.scanner_v2.universe import load_canonical_universe


def parser():
    command = argparse.ArgumentParser(description="Research-only Global Scanner v2 market-data acquisition")
    selection = command.add_mutually_exclusive_group(required=True)
    selection.add_argument("--universe")
    selection.add_argument("--all-enabled", action="store_true")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--universe-dir", default="data/universes")
    command.add_argument("--store-dir", default="data/global_scanner/bar_store")
    command.add_argument("--batch-size", type=int, default=50)
    command.add_argument("--max-attempts", type=int, default=3)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    universe, memberships = load_canonical_universe(args.universe_dir)
    if args.universe:
        selected = set(memberships.loc[memberships["universe_name"].eq(args.universe), "ticker"])
        if not selected:
            raise SystemExit(f"Unknown or empty universe: {args.universe}")
        universe = universe[universe["ticker"].isin(selected)].copy()
    config = AcquisitionConfig(batch_size=args.batch_size, max_attempts=args.max_attempts)
    store = ScannerBarStore(args.store_dir)
    now = pd.Timestamp.now(tz="UTC")
    plan = build_acquisition_plan(universe, store, now, config)
    print(plan.to_string(index=False))
    if args.dry_run:
        print(f"dry_run=true planned_symbols={len(plan)} downloads=0 writes=0")
        return 0

    configure_scanner_yfinance_cache(args.store_dir)
    started = pd.Timestamp.now(tz="UTC")
    results, updates, retries = acquire_plan(plan, YFinanceDownloader(), started, config)
    run_id = uuid4().hex
    stats = {
        ticker: merge_bars(store.read(ticker), bars, ticker)[1]
        for ticker, bars in updates.items()
    }
    manifest = acquisition_manifest(plan, results, stats, started, pd.Timestamp.now(tz="UTC"), retries, run_id)
    rejected = results[results["status"].isin(["failed", "rejected", "stale_cache"])].copy()
    store.commit(
        updates,
        generation_id=run_id,
        csv_artifacts={
            "scanner_download_results.csv": results,
            "scanner_rejected_assets.csv": rejected,
        },
        json_artifacts={
            "scanner_acquisition_plan.json": {
                "run_id": run_id,
                "plan": plan.astype(object).where(pd.notna(plan), None).to_dict(orient="records"),
            },
            "scanner_acquisition_manifest.json": manifest,
        },
    )
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
