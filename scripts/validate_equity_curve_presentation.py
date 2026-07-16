from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.equity_chart import build_equity_curve_layers


def main():
    data = pd.DataFrame(
        [
            {"challenge_day": 0, "portfolio_value": 10000.0, "is_recorded": False, "recorded_run": None},
            {"challenge_day": 1, "portfolio_value": 10010.0, "is_recorded": True, "recorded_run": 1},
            {"challenge_day": 2, "portfolio_value": 10010.0, "is_recorded": False, "recorded_run": None},
            {"challenge_day": 3, "portfolio_value": 10043.48, "is_recorded": True, "recorded_run": 2},
        ]
    )
    encoding = {
        "x": alt.X("challenge_day:O"),
        "y": alt.Y("portfolio_value:Q"),
    }
    chart = build_equity_curve_layers(
        data,
        encoding,
        [alt.Tooltip("portfolio_value:Q")],
    ).to_dict()
    layers = chart["layer"]
    checks = {
        "four presentation layers are emitted": len(layers) == 4,
        "continuity is light dashed and subordinate": layers[0]["mark"]["color"] == "#94A3B8" and layers[0]["mark"]["strokeDash"] == [4, 5] and layers[0]["mark"]["opacity"] == 0.35,
        "continuity has no tooltip": "tooltip" not in layers[0].get("encoding", {}),
        "recorded line is solid blue": layers[1]["mark"]["color"] == "#2563EB" and "strokeDash" not in layers[1]["mark"],
        "recorded markers filter synthetic days": "is_recorded" in str(layers[2].get("transform", [])),
        "final marker is larger than recorded markers": layers[3]["mark"]["size"] > layers[2]["mark"]["size"],
        "latest recorded day is emphasised": "3" in str(layers[3].get("transform", [])),
        "chart construction does not mutate values": float(data.iloc[-1]["portfolio_value"]) == 10043.48 and len(data) == 4,
    }
    for message, passed in checks.items():
        print(("PASS" if passed else "FAIL") + f": {message}")
    failures = sum(not passed for passed in checks.values())
    print(f"summary={failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
