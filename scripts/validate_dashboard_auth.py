from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ui.auth as auth


class StopCalled(Exception):
    pass


class FakeSidebar:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def caption(self, *_args, **_kwargs):
        pass

    def button(self, *_args, **_kwargs):
        return False


class FakeForm:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeSecrets(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.secrets = FakeSecrets()
        self.sidebar = FakeSidebar()
        self.errors = []
        self.warnings = []
        self.forms = []
        self.markdown_calls = []

    def error(self, message):
        self.errors.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def stop(self):
        raise StopCalled()

    def markdown(self, message, **_kwargs):
        self.markdown_calls.append(str(message))

    def form(self, key):
        self.forms.append(str(key))
        return FakeForm()

    def text_input(self, *_args, **_kwargs):
        return ""

    def form_submit_button(self, *_args, **_kwargs):
        return False

    def rerun(self):
        raise StopCalled()

    def caption(self, *_args, **_kwargs):
        pass

    def button(self, *_args, **_kwargs):
        return False


def clear_auth_env():
    for key in (
        "DASHBOARD_PASSWORD",
        "GARNER_QUANT_DASHBOARD_PASSWORD",
        "DASHBOARD_ALLOW_LOCAL_NO_PASSWORD",
        "GARNER_QUANT_SHOW_AUTH_DEV_WARNING",
        "GARNER_QUANT_ENV",
        "DASHBOARD_ENV",
        "APP_ENV",
        "ENVIRONMENT",
        "ENV",
        "AWS_EXECUTION_ENV",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "EB_ENVIRONMENT_NAME",
        "ECS_CONTAINER_METADATA_URI",
        "ECS_CONTAINER_METADATA_URI_V4",
    ):
        os.environ.pop(key, None)


def check(condition, message, issues):
    if condition:
        print(f"OK: {message}")
    else:
        print(f"FAIL: {message}")
        issues.append(message)


def assert_stops(func):
    try:
        func()
    except StopCalled:
        return True
    return False


def validate_auth_behaviour(issues):
    original_st = auth.st
    try:
        fake = FakeStreamlit()
        auth.st = fake
        clear_auth_env()
        os.environ["ENVIRONMENT"] = "production"
        stopped = assert_stops(auth.require_dashboard_login)
        check(stopped, "production without DASHBOARD_PASSWORD stops", issues)
        check(fake.errors, "production without password shows locked error", issues)

        fake = FakeStreamlit()
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        stopped = assert_stops(auth.require_dashboard_login)
        check(stopped, "unauthenticated password-protected dashboard stops", issues)
        check(
            "gq_dashboard_login" in fake.forms,
            "unauthenticated user sees login form",
            issues,
        )

        fake = FakeStreamlit()
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_ALLOW_LOCAL_NO_PASSWORD"] = "true"
        allowed = auth.require_dashboard_login()
        check(allowed is True, "explicit local no-password mode is allowed", issues)
    finally:
        auth.st = original_st
        clear_auth_env()


def validate_entrypoint_order(issues):
    entrypoints = {
        ROOT / "web_dashboard.py": "broker = load_home_table(",
        ROOT / "pages" / "04_trade_audit.py": "st.title(",
        ROOT / "pages" / "96_backtest_analytics.py": "analytics = load_backtest_analytics(",
        ROOT / "pages" / "97_research_intelligence.py": "insights = generate_research_insights(",
        ROOT / "pages" / "98_research_lab.py": "data = {}",
        ROOT / "pages" / "99_admin_health.py": "data = {}",
    }

    for path, marker in entrypoints.items():
        text = path.read_text(encoding="utf-8")
        auth_index = text.find("require_dashboard_login()")
        marker_index = text.find(marker)
        check(auth_index >= 0, f"{path.name} calls require_dashboard_login", issues)
        check(marker_index >= 0, f"{path.name} has protected data/content marker", issues)
        check(
            marker_index >= 0 and auth_index < marker_index,
            f"{path.name} authenticates before top-level dashboard content/data loads",
            issues,
        )


def main():
    issues = []
    validate_auth_behaviour(issues)
    validate_entrypoint_order(issues)
    print(f"summary={len(issues)} issue(s)")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
