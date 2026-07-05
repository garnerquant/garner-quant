from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.bootstrap_state import bootstrap_runtime_state  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Create missing generated runtime state files with safe seed schemas. "
            "Existing files are never overwritten."
        )
    )
    parser.add_argument("--root", default=str(ROOT), help="Project root to seed.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write missing seed files. Without this, only prints the plan.",
    )
    args = parser.parse_args(argv)

    result = bootstrap_runtime_state(Path(args.root), apply=args.apply)
    mode = "APPLY" if args.apply else "DRY_RUN"
    print(f"runtime_bootstrap_mode={mode}")
    print(f"existing={len(result.existing)}")
    print(f"planned={len(result.planned)}")
    print(f"created={len(result.created)}")
    for path in result.created if args.apply else result.planned:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
