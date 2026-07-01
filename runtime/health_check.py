from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT_DIR / "data" / "live_runtime_status.json"
DEFAULT_STALE_SECONDS = 10 * 60


def parse_timestamp(value):
    if not value:
        return None

    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_status(path):
    path = Path(path)
    if not path.exists():
        return None, f"status file not found: {path}"

    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"status file is invalid JSON: {exc}"
    except OSError as exc:
        return None, f"status file could not be read: {exc}"


def heartbeat_age_seconds(status, now):
    heartbeat = parse_timestamp(status.get("last_cycle_at"))
    if heartbeat is None:
        return None
    return max(0.0, (now - heartbeat).total_seconds())


def format_age(seconds):
    if seconds is None:
        return "unknown"

    seconds = int(seconds)
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}h {minutes}m {remainder}s"
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"


def evaluate_health(status, stale_seconds):
    now = datetime.now(timezone.utc)
    runtime_status = status.get("status", "unknown")
    last_error = status.get("last_error")
    cycle_count = status.get("cycle_count", 0)
    age_seconds = heartbeat_age_seconds(status, now)
    stale = age_seconds is None or age_seconds > stale_seconds

    problems = []
    if runtime_status != "running":
        problems.append(f"runtime status is {runtime_status}")
    if stale:
        problems.append("heartbeat is stale or missing")
    if last_error:
        problems.append(f"last error: {last_error}")

    return {
        "healthy": not problems,
        "runtime_status": runtime_status,
        "heartbeat_age_seconds": age_seconds,
        "heartbeat_age": format_age(age_seconds),
        "heartbeat_stale": stale,
        "last_error": last_error,
        "cycle_count": cycle_count,
        "problems": problems,
    }


def print_report(result):
    print(f"Runtime status: {result['runtime_status']}")
    print(f"Last heartbeat age: {result['heartbeat_age']}")
    print(f"Heartbeat stale: {result['heartbeat_stale']}")
    print(f"Last error: {result['last_error'] or 'None'}")
    print(f"Cycle count: {result['cycle_count']}")

    if result["healthy"]:
        print("Health: healthy")
    else:
        print("Health: unhealthy")
        for problem in result["problems"]:
            print(f"- {problem}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check Garner Quant live runtime health."
    )
    parser.add_argument(
        "--status-file",
        default=STATUS_FILE,
        help="Path to live_runtime_status.json.",
    )
    parser.add_argument(
        "--stale-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help="Heartbeat stale threshold in seconds. Default: 600.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    status, error = load_status(args.status_file)
    if error:
        print("Runtime status: unknown")
        print("Last heartbeat age: unknown")
        print("Heartbeat stale: True")
        print("Last error: None")
        print("Cycle count: 0")
        print("Health: unhealthy")
        print(f"- {error}")
        return 1

    result = evaluate_health(status, args.stale_seconds)
    print_report(result)
    return 0 if result["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
