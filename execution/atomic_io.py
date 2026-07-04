from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4


ATOMIC_ARTIFACT_PATTERNS = (
    ".*.atomic-*.tmp",
    ".*.atomic-*.bak",
)


class AtomicWriteError(RuntimeError):
    pass


@dataclass(frozen=True)
class AtomicCsvTarget:
    final_path: Path
    temp_path: Path
    backup_path: Path


def atomic_artifact_paths(root_dir="."):
    root = Path(root_dir)
    search_dirs = [root, root / "data"]

    for directory in search_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for pattern in ATOMIC_ARTIFACT_PATTERNS:
            yield from directory.glob(pattern)


def assert_no_atomic_artifacts(root_dir="."):
    artifacts = sorted(str(path) for path in atomic_artifact_paths(root_dir))
    if artifacts:
        raise AtomicWriteError(
            "Unfinished atomic write artifacts found: " + ", ".join(artifacts)
        )


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
