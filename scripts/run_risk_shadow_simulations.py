from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from risk_engine.shadow_simulation import run_shadow_simulations


def main():
    parser = argparse.ArgumentParser(description="Run non-executing risk shadow scenarios")
    parser.add_argument("--output-dir", required=True, help="Isolated output directory")
    args = parser.parse_args()
    report = run_shadow_simulations(args.output_dir)
    print(f"PASS: {len(report['scenarios'])} shadow scenarios; execution_attempts=0")


if __name__ == "__main__":
    main()
