from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from execution.atomic_io import recover_atomic_artifacts
from runtime.bootstrap_state import bootstrap_runtime_state


MANIFEST_FILE = ROOT_DIR / "runtime" / "generated_runtime_files.txt"
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


@dataclass
class RuntimeValidationResult:
    checked_files: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


class RuntimeStartupValidationError(RuntimeError):
    pass


def load_generated_runtime_paths(manifest_path=MANIFEST_FILE):
    manifest_path = Path(manifest_path)
    paths = []

    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(line)

    return paths


def iter_existing_generated_files(root_dir=ROOT_DIR, manifest_path=MANIFEST_FILE):
    root_dir = Path(root_dir)

    for relative_path in load_generated_runtime_paths(manifest_path):
        normalized_path = relative_path.replace("\\", "/")
        absolute_path = root_dir / normalized_path.rstrip("/")
        if normalized_path.endswith("/"):
            if not absolute_path.exists():
                continue
            yield from (
                path
                for path in absolute_path.rglob("*")
                if path.is_file() and path.suffix.lower() in {".csv", ".json"}
            )
            continue

        if absolute_path.exists() and absolute_path.is_file():
            yield absolute_path


def relative_display_path(path, root_dir=ROOT_DIR):
    try:
        return str(Path(path).resolve().relative_to(Path(root_dir).resolve()))
    except Exception:
        return str(path)


def file_contains_conflict_marker(path):
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if any(stripped.startswith(marker) for marker in CONFLICT_MARKERS):
                return True
    except Exception:
        return False

    return False


def validate_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return

        expected_columns = len(header)
        for row_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != expected_columns:
                raise ValueError(
                    f"row {row_number} has {len(row)} columns; "
                    f"expected {expected_columns}"
                )


def validate_json(path):
    json.loads(Path(path).read_text(encoding="utf-8"))


def validate_runtime_generated_files(root_dir=ROOT_DIR, manifest_path=MANIFEST_FILE):
    errors = []
    checked_files = 0

    for path in iter_existing_generated_files(root_dir, manifest_path):
        checked_files += 1
        display_path = relative_display_path(path, root_dir)

        if file_contains_conflict_marker(path):
            errors.append(f"{display_path}: contains git conflict markers")
            continue

        try:
            if path.suffix.lower() == ".csv":
                validate_csv(path)
            elif path.suffix.lower() == ".json":
                validate_json(path)
        except Exception as exc:
            errors.append(f"{display_path}: invalid {path.suffix.lower()} ({exc})")

    return RuntimeValidationResult(checked_files=checked_files, errors=errors)


def validate_runtime_startup(root_dir=ROOT_DIR, manifest_path=MANIFEST_FILE):
    recover_atomic_artifacts(root_dir)
    bootstrap_runtime_state(root_dir, apply=True)
    result = validate_runtime_generated_files(root_dir, manifest_path)
    if not result.ok:
        details = "\n".join(f"- {error}" for error in result.errors)
        raise RuntimeStartupValidationError(
            "Runtime startup refused because generated runtime data is corrupted "
            "or contains git conflict markers:\n"
            f"{details}\n\n"
            "Stop the runtime, recover the affected generated files, then start "
            "the runtime again."
        )
    accounting_pointer = (
        Path(root_dir)
        / "data"
        / "accounting_generations"
        / "accounting_generation.json"
    )
    if accounting_pointer.exists():
        try:
            from canonical_accounting.generation import load_active_generation
            load_active_generation(accounting_pointer.parent)
        except Exception as exc:
            raise RuntimeStartupValidationError(
                "Runtime startup refused because the active canonical accounting "
                f"generation is invalid: {exc}"
            ) from exc
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate Garner Quant generated runtime files before startup."
    )
    parser.add_argument(
        "--root",
        default=str(ROOT_DIR),
        help="Project root to validate.",
    )
    args = parser.parse_args(argv)

    try:
        result = validate_runtime_startup(Path(args.root))
    except RuntimeStartupValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Runtime generated data validation passed ({result.checked_files} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
