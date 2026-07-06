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
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def caption(self, *_args, **_kwargs):
        pass

    def button(self, *_args, **_kwargs):
        return self.app.logout_clicked


class FakeForm:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeSecrets(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeStreamlit:
    def __init__(self, *, password_input="", submit=False, logout_clicked=False, cookies=None):
        self.session_state = {}
        self.secrets = FakeSecrets()
        self.sidebar = FakeSidebar(self)
        self.errors = []
        self.warnings = []
        self.forms = []
        self.markdown_calls = []
        self.successes = []
        self.password_input = password_input
        self.submit = submit
        self.logout_clicked = logout_clicked
        self.context = type(
            "FakeContext",
            (),
            {
                "cookies": cookies or {},
                "url": "https://dashboard.example.com",
            },
        )()

    def error(self, message):
        self.errors.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def success(self, message):
        self.successes.append(str(message))

    def stop(self):
        raise StopCalled()

    def markdown(self, message, **_kwargs):
        self.markdown_calls.append(str(message))

    def form(self, key):
        self.forms.append(str(key))
        return FakeForm()

    def text_input(self, *_args, **_kwargs):
        return self.password_input

    def form_submit_button(self, *_args, **_kwargs):
        return self.submit

    def rerun(self):
        raise StopCalled()

    def caption(self, *_args, **_kwargs):
        pass

    def button(self, *_args, **_kwargs):
        return self.logout_clicked


def clear_auth_env():
    for key in (
        "DASHBOARD_PASSWORD",
        "GARNER_QUANT_DASHBOARD_PASSWORD",
        "DASHBOARD_AUTH_SECRET",
        "DASHBOARD_SESSION_DAYS",
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
    original_components = auth.components
    cookie_writes = []

    class FakeComponents:
        @staticmethod
        def html(markup, **_kwargs):
            cookie_writes.append(str(markup))

    try:
        auth.components = FakeComponents()

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

        fake = FakeStreamlit(password_input="wrong", submit=True)
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        stopped = assert_stops(auth.require_dashboard_login)
        check(stopped, "wrong password remains on login screen", issues)
        check(
            not fake.session_state.get(auth.AUTH_SESSION_KEY),
            "wrong password does not authenticate session",
            issues,
        )

        fake = FakeStreamlit(password_input="secret", submit=True)
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        os.environ["DASHBOARD_AUTH_SECRET"] = "test-auth-secret"
        os.environ["DASHBOARD_SESSION_DAYS"] = "7"
        stopped = assert_stops(auth.require_dashboard_login)
        token = fake.session_state.get(auth.AUTH_PENDING_TOKEN_KEY)
        check(stopped, "correct password triggers authenticated rerun", issues)
        check(
            fake.session_state.get(auth.AUTH_SESSION_KEY) is True,
            "correct password authenticates session",
            issues,
        )
        check(bool(token), "correct password creates persistent signed token", issues)
        check(
            token and auth.validate_auth_token(token, "secret"),
            "created token validates",
            issues,
        )

        fake = FakeStreamlit(cookies={auth.AUTH_TOKEN_COOKIE: token})
        auth.st = fake
        cookie_writes.clear()
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        os.environ["DASHBOARD_AUTH_SECRET"] = "test-auth-secret"
        allowed = auth.require_dashboard_login()
        check(allowed is True, "new app run remains authenticated with valid cookie", issues)
        check(
            fake.session_state.get(auth.AUTH_SESSION_KEY) is True,
            "valid cookie restores authenticated session",
            issues,
        )

        expired = auth.build_auth_token("secret", now=100, session_days=1)
        fake = FakeStreamlit(cookies={auth.AUTH_TOKEN_COOKIE: expired})
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        os.environ["DASHBOARD_AUTH_SECRET"] = "test-auth-secret"
        stopped = assert_stops(lambda: auth.require_dashboard_login())
        check(stopped, "expired token is rejected", issues)
        check("gq_dashboard_login" in fake.forms, "expired token shows login form", issues)

        fake = FakeStreamlit(cookies={auth.AUTH_TOKEN_COOKIE: "invalid.token"})
        auth.st = fake
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        os.environ["DASHBOARD_AUTH_SECRET"] = "test-auth-secret"
        stopped = assert_stops(lambda: auth.require_dashboard_login())
        check(stopped, "invalid token is rejected", issues)
        check("gq_dashboard_login" in fake.forms, "invalid token shows login form", issues)

        fake = FakeStreamlit(logout_clicked=True)
        fake.session_state[auth.AUTH_SESSION_KEY] = True
        fake.session_state[auth.AUTH_FINGERPRINT_KEY] = auth._password_fingerprint("secret")
        auth.st = fake
        cookie_writes.clear()
        clear_auth_env()
        os.environ["DASHBOARD_PASSWORD"] = "secret"
        stopped = assert_stops(lambda: auth.require_dashboard_login())
        check(stopped, "logout stops before dashboard content", issues)
        check(
            not fake.session_state.get(auth.AUTH_SESSION_KEY),
            "logout clears authenticated session",
            issues,
        )
        check(
            any(f"{auth.AUTH_TOKEN_COOKIE}=;" in item for item in cookie_writes),
            "logout emits cookie clear script",
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
        auth.components = original_components
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
