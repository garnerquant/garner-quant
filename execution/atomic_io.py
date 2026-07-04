from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
import re
from uuid import uuid4


ATOMIC_ARTIFACT_PATTERNS = (
    ".*.atomic-*.tmp",
    ".*.atomic-*.bak",
)


class AtomicWriteError(RuntimeError):
    pass


class AtomicRecoveryError(AtomicWriteError):
    pass


@dataclass(frozen=True)
class AtomicCsvTarget:
    final_path: Path
    temp_path: Path
    backup_path: Path


@dataclass(frozen=True)
class AtomicArtifact:
    path: Path
    final_path: Path
    transaction_id: str
    kind: str


ATOMIC_ARTIFACT_RE = re.compile(
    r"^\.(?P<name>.+)\.atomic-(?P<transaction_id>[0-9a-f]+)\.(?P<kind>tmp|bak)$"
)


def atomic_artifact_paths(root_dir="."):
    root = Path(root_dir)
    search_dirs = [root, root / "data"]

    for directory in search_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for pattern in ATOMIC_ARTIFACT_PATTERNS:
            yield from directory.glob(pattern)


def parse_atomic_artifact(path):
    path = Path(path)
    match = ATOMIC_ARTIFACT_RE.match(path.name)
    if not match:
        return None
    return AtomicArtifact(
        path=path,
        final_path=path.with_name(match.group("name")),
        transaction_id=match.group("transaction_id"),
        kind=match.group("kind"),
    )


def atomic_artifacts(root_dir="."):
    for path in atomic_artifact_paths(root_dir):
        artifact = parse_atomic_artifact(path)
        if artifact is not None:
            yield artifact


def assert_no_atomic_artifacts(root_dir="."):
    artifacts = sorted(str(path) for path in atomic_artifact_paths(root_dir))
    if artifacts:
        raise AtomicWriteError(
            "Unfinished atomic write artifacts found: " + ", ".join(artifacts)
        )


def validate_atomic_final(path, final_path=None):
    path = Path(path)
    validation_path = Path(final_path) if final_path is not None else path
    if not path.exists():
        raise AtomicRecoveryError(f"Atomic recovery expected final file: {path}")

    suffix = validation_path.suffix.lower()
    if suffix == ".json":
        json.loads(path.read_text(encoding="utf-8"))
        return
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                return
            expected_columns = len(header)
            for row_number, row in enumerate(reader, start=2):
                if not row or all(not cell.strip() for cell in row):
                    continue
                if len(row) != expected_columns:
                    raise AtomicRecoveryError(
                        f"{path} row {row_number} has {len(row)} columns; "
                        f"expected {expected_columns}"
                    )
        return

    raise AtomicRecoveryError(
        f"Atomic recovery cannot validate unsupported file type: {validation_path}"
    )


def recover_atomic_artifacts(root_dir="."):
    grouped = {}
    for artifact in atomic_artifacts(root_dir):
        key = (artifact.final_path.resolve(), artifact.transaction_id)
        grouped.setdefault(key, []).append(artifact)

    actions = []
    errors = []

    for (_final_resolved, transaction_id), artifacts_for_target in grouped.items():
        final_path = artifacts_for_target[0].final_path
        temp_paths = [a.path for a in artifacts_for_target if a.kind == "tmp"]
        backup_paths = [a.path for a in artifacts_for_target if a.kind == "bak"]

        if len(temp_paths) > 1 or len(backup_paths) > 1:
            errors.append(
                f"{final_path}: ambiguous duplicate atomic artifacts for "
                f"transaction {transaction_id}"
            )
            continue

        temp_path = temp_paths[0] if temp_paths else None
        backup_path = backup_paths[0] if backup_paths else None
        final_exists = final_path.exists()

        try:
            if backup_path is not None and not final_exists:
                validate_atomic_final(backup_path, final_path=final_path)
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
                    actions.append(f"removed temp for {final_path}")
                backup_path.replace(final_path)
                actions.append(f"restored backup for {final_path}")
                continue

            if final_exists:
                validate_atomic_final(final_path)
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
                    actions.append(f"removed temp for {final_path}")
                if backup_path is not None and backup_path.exists():
                    backup_path.unlink()
                    actions.append(f"removed backup for {final_path}")
                continue

            if temp_path is not None and backup_path is None:
                errors.append(
                    f"{final_path}: temp artifact exists but final and backup are missing"
                )
                continue

            errors.append(f"{final_path}: unsupported atomic artifact state")
        except Exception as exc:
            errors.append(f"{final_path}: recovery failed ({exc})")

    if errors:
        raise AtomicRecoveryError(
            "Atomic recovery failed; operator intervention required: "
            + "; ".join(errors)
        )

    return actions


def _target_for(path, transaction_id):
    final_path = Path(path)
    return AtomicCsvTarget(
        final_path=final_path,
        temp_path=final_path.with_name(
            f".{final_path.name}.atomic-{transaction_id}.tmp"
        ),
        backup_path=final_path.with_name(
            f".{final_path.name}.atomic-{transaction_id}.bak"
        ),
    )


def atomic_write_csv_frames(
    frames_by_path,
    *,
    failure_hook=None,
    default_to_csv_kwargs=None,
    to_csv_kwargs_by_path=None,
):
    if not frames_by_path:
        return []

    frames = {Path(path): frame for path, frame in frames_by_path.items()}
    default_kwargs = (
        {"index": False}
        if default_to_csv_kwargs is None
        else dict(default_to_csv_kwargs)
    )
    per_path_kwargs = {
        Path(path): dict(kwargs)
        for path, kwargs in (to_csv_kwargs_by_path or {}).items()
    }
    transaction_id = uuid4().hex
    targets = [_target_for(path, transaction_id) for path in frames]
    final_paths = [target.final_path.resolve() for target in targets]
    if len(final_paths) != len(set(final_paths)):
        raise AtomicWriteError("Atomic CSV commit received duplicate output paths.")

    replaced = []
    backups = []

    try:
        for target in targets:
            target.final_path.parent.mkdir(parents=True, exist_ok=True)
            csv_kwargs = dict(default_kwargs)
            csv_kwargs.update(per_path_kwargs.get(target.final_path, {}))
            frames[target.final_path].to_csv(target.temp_path, **csv_kwargs)

        if failure_hook:
            failure_hook("after_temp_writes", targets)

        for target in targets:
            if failure_hook:
                failure_hook("before_replace", target)

            if target.final_path.exists():
                target.final_path.replace(target.backup_path)
                backups.append(target)

            target.temp_path.replace(target.final_path)
            replaced.append(target)

            if failure_hook:
                failure_hook("after_replace", target)

        for target in backups:
            if target.backup_path.exists():
                target.backup_path.unlink()

        return [target.final_path for target in targets]

    except Exception as exc:
        for target in reversed(replaced):
            if target.final_path.exists():
                target.final_path.unlink()

        for target in reversed(backups):
            if target.backup_path.exists():
                target.backup_path.replace(target.final_path)

        raise AtomicWriteError(f"Atomic CSV commit failed and was rolled back: {exc}") from exc

    finally:
        for target in targets:
            if target.temp_path.exists():
                target.temp_path.unlink()
            if target.backup_path.exists():
                target.backup_path.unlink()


def atomic_write_json(
    data,
    path,
    *,
    failure_hook=None,
    json_kwargs=None,
):
    json_kwargs = (
        {"indent": 2}
        if json_kwargs is None
        else dict(json_kwargs)
    )
    target = _target_for(path, uuid4().hex)
    replaced = False
    backed_up = False

    try:
        target.final_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, **json_kwargs)
        target.temp_path.write_text(payload, encoding="utf-8")
        json.loads(target.temp_path.read_text(encoding="utf-8"))

        if failure_hook:
            failure_hook("after_temp_write", target)

        if target.final_path.exists():
            target.final_path.replace(target.backup_path)
            backed_up = True

        target.temp_path.replace(target.final_path)
        replaced = True

        if failure_hook:
            failure_hook("after_replace", target)

        if target.backup_path.exists():
            target.backup_path.unlink()

        return target.final_path

    except Exception as exc:
        if replaced and target.final_path.exists():
            target.final_path.unlink()
        if backed_up and target.backup_path.exists():
            target.backup_path.replace(target.final_path)
        raise AtomicWriteError(
            f"Atomic JSON write failed and was rolled back: {exc}"
        ) from exc

    finally:
        if target.temp_path.exists():
            target.temp_path.unlink()
        if target.backup_path.exists():
            target.backup_path.unlink()
