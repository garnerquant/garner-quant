from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from risk_engine.kill_switch import load_kill_switch, set_kill_switch  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect or explicitly change the central risk kill switch.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    for command in ("activate", "clear"):
        item = subparsers.add_parser(command)
        item.add_argument("--actor", required=True)
        item.add_argument("--reason", required=True)
        item.add_argument("--correlation-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "status":
        state = load_kill_switch()
    else:
        state = set_kill_switch(
            args.command == "activate",
            actor=args.actor,
            reason=args.reason,
            correlation_id=args.correlation_id,
        )
    print(json.dumps(state.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
