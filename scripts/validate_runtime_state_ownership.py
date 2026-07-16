from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check(condition, message, issues):
    print(("PASS" if condition else "FAIL") + f": {message}")
    if not condition:
        issues.append(message)


def tracked_ignored_files():
    result = subprocess.run(
        ["git", "ls-files", "-c", "-i", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main():
    issues = []
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    daily = (ROOT / ".github" / "workflows" / "daily_bot.yml").read_text(encoding="utf-8")
    mark = (ROOT / "execution" / "mark_to_market.py").read_text(encoding="utf-8")

    check(not tracked_ignored_files(), "Git owns no ignored runtime state files", issues)
    check(
        "Preserving server-owned runtime state" in deploy
        and "runtime/generated_runtime_files.txt" in deploy
        and "Restoring server-owned runtime state" in deploy,
        "deployment preserves runtime state across source reset",
        issues,
    )
    reset_at = deploy.index("git reset --hard origin/main")
    restore_at = deploy.index("Restoring server-owned runtime state")
    validation_at = deploy.index("Running startup validation")
    check(reset_at < restore_at < validation_at, "deployment restores state before startup validation", issues)
    check("git add -u" not in daily and "git push" not in daily, "daily Actions run cannot publish runtime state", issues)
    check("contents: read" in daily, "daily Actions workflow has read-only repository permission", issues)
    check(
        "python main_v2.py" not in daily
        and "SUPABASE_URL" not in daily
        and "Validate accounting architecture" in daily,
        "daily Actions workflow cannot execute or remotely sync an alternate account",
        issues,
    )
    refresh_block = mark.split("refresh_frames = {", 1)[1].split("}", 1)[0]
    check("PORTFOLIO_FILE:" not in refresh_block, "derived mark-to-market does not own paper portfolio", issues)

    print(f"summary={len(issues)} failure(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
