"""Run one explicitly supplied, offline, non-authoritative shadow comparison."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import sys


def _bootstrap_repository_imports():
    if __package__ in (None, ""):
        repository_root = Path(__file__).resolve().parents[1]
        repository_root_text = str(repository_root)
        if repository_root_text not in sys.path:
            sys.path.insert(0, repository_root_text)


_bootstrap_repository_imports()

from research import shadow_input as _shadow_input
from research import shadow_report as _shadow_report
from research import shadow_runner as _shadow_runner


_export_shadow_report = _shadow_report.export_shadow_report
_verify_shadow_report = _shadow_report.verify_shadow_report

EXIT_OK = 0
EXIT_ARGUMENTS = 2
EXIT_INPUT = 3
EXIT_DECODING = 4
EXIT_RUNNER = 5
EXIT_EXPORT = 6
EXIT_VERIFICATION = 7

_REPARSE_POINT = 0x400
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class _ParserExit(Exception):
    def __init__(self, status):
        self.status = status


class _ParserError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser whose output and exits are controllable by main()."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._output = sys.stdout
        self._errors = sys.stderr

    def _print_message(self, message, file=None):
        if message:
            (self._output if file is None or file is sys.stdout else file).write(message)

    def exit(self, status=0, message=None):
        if message:
            self._errors.write(message)
        raise _ParserExit(status)

    def error(self, message):
        raise _ParserError(message)


def build_parser():
    """Build the CLI parser without reading files or consulting process state."""
    parser = _ArgumentParser(
        prog="run_shadow_research",
        description="Run one manually supplied offline shadow comparison.",
    )
    parser.add_argument("--input", required=True, help="explicit shadow-input JSON file")
    parser.add_argument("--export", action="store_true", help="request an immutable evidence export")
    parser.add_argument("--output-root", help="explicit external export root (required with --export)")
    parser.add_argument("--export-id", help="caller-supplied export namespace ID (required with --export)")
    parser.add_argument("--export-created-at", help="caller-supplied UTC export timestamp (required with --export)")
    parser.add_argument("--operator-purpose", help="bounded operator purpose (required with --export)")
    return parser


def _emit_error(stream, category, code, reason):
    stream.write(json.dumps(
        {"category": category, "exit_code": code, "reason": reason},
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n")


def _argument_error(args):
    export_options = (args.output_root, args.export_id, args.export_created_at, args.operator_purpose)
    if not args.export and any(value is not None for value in export_options):
        return "export options require --export"
    if args.export and any(value is None for value in export_options):
        return "--export requires output-root, export-id, export-created-at and operator-purpose"
    return None


def _safe_read_input(value):
    """Read only the explicitly named regular, non-link input file."""
    if not isinstance(value, str) or not value:
        raise ValueError("an explicit input file is required")
    path = Path(value)
    try:
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
            raise ValueError("input file must not be a symbolic link")
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("input path must be a regular file")
        if info.st_size > _shadow_input.MAX_INPUT_BYTES:
            raise ValueError("input file exceeds the maximum size")
        with path.open("rb") as handle:
            raw = handle.read(_shadow_input.MAX_INPUT_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ValueError("input file cannot be read safely") from exc
    if len(raw) > _shadow_input.MAX_INPUT_BYTES:
        raise ValueError("input file exceeds the maximum size")
    return raw


def _utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("export-created-at must be a UTC timestamp")
    try:
        parsed = datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError("export-created-at must use canonical UTC form") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _summary(decoded, result, *, export_requested, export_verified, export_id=None):
    summary = {
        "schema_version": decoded.schema_version,
        "request_type": decoded.request_type,
        "shadow_run_id": decoded.request.shadow_run_id,
        "raw_input_sha256": decoded.raw_input_sha256,
        "canonical_input_sha256": decoded.canonical_input_sha256,
        "shadow_result_sha256": result.canonical_sha256,
        "result_classification": result.result_classification,
        "compared_instrument_count": result.comparison_summary.compared_count,
        "outcome_counts": dict(result.comparison_summary.outcome_counts),
        "unavailable_or_rejected_count": len(result.unavailable_inputs),
        "execution_authorized": False,
        "publication_authorized": False,
        "runtime_effect": False,
        "paper_effect": False,
        "accounting_effect": False,
        "export_requested": export_requested,
        "export_verified": export_verified,
    }
    if export_id is not None:
        summary["export_id"] = export_id
    return summary


def _emit_summary(stream, summary):
    stream.write(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv=None, stdout=None, stderr=None):
    """Run the explicitly requested offline comparison and optional export."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()
    parser._output = stdout
    parser._errors = stderr
    try:
        args = parser.parse_args(argv)
    except _ParserExit as exc:
        return exc.status
    except _ParserError as exc:
        _emit_error(stderr, "invalid_arguments", EXIT_ARGUMENTS, str(exc))
        return EXIT_ARGUMENTS

    reason = _argument_error(args)
    if reason:
        _emit_error(stderr, "invalid_arguments", EXIT_ARGUMENTS, reason)
        return EXIT_ARGUMENTS

    try:
        raw = _safe_read_input(args.input)
    except (OSError, ValueError):
        _emit_error(stderr, "input_error", EXIT_INPUT, "explicit input file could not be read safely")
        return EXIT_INPUT

    try:
        decoded = _shadow_input.decode_shadow_input(raw)
    except Exception:
        _emit_error(stderr, "input_validation_error", EXIT_DECODING, "input failed strict shadow schema validation")
        return EXIT_DECODING

    try:
        result = _shadow_runner.run_shadow_comparison(decoded.request)
    except Exception:
        _emit_error(stderr, "shadow_runner_error", EXIT_RUNNER, "shadow comparison failed")
        return EXIT_RUNNER

    verified = False
    if args.export:
        try:
            created_at = _utc_timestamp(args.export_created_at)
            namespace = _export_shadow_report(
                result=result,
                output_root=args.output_root,
                export_id=args.export_id,
                created_at=created_at,
                operator_purpose=args.operator_purpose,
                code_version=decoded.request.code_version,
                raw_input_sha256=decoded.raw_input_sha256,
                canonical_input_sha256=decoded.canonical_input_sha256,
            )
        except Exception:
            _emit_error(stderr, "export_error", EXIT_EXPORT, "shadow report export failed")
            return EXIT_EXPORT
        try:
            verified = bool(_verify_shadow_report(namespace))
        except Exception:
            verified = False
        if not verified:
            _emit_error(stderr, "export_verification_error", EXIT_VERIFICATION, "shadow report verification failed")
            return EXIT_VERIFICATION

    _emit_summary(stdout, _summary(
        decoded,
        result,
        export_requested=args.export,
        export_verified=verified,
        export_id=args.export_id if args.export else None,
    ))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
