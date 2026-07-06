import hashlib
import hmac
import base64
import json
import os
import time

import streamlit as st
import streamlit.components.v1 as components

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


AUTH_SESSION_KEY = "gq_dashboard_authenticated"
AUTH_FINGERPRINT_KEY = "gq_dashboard_auth_fingerprint"
AUTH_TOKEN_COOKIE = "gq_dashboard_auth"
AUTH_PENDING_TOKEN_KEY = "gq_dashboard_pending_auth_token"
AUTH_PENDING_CLEAR_KEY = "gq_dashboard_pending_auth_clear"
DEV_WARNING_ENV_VAR = "GARNER_QUANT_SHOW_AUTH_DEV_WARNING"
LOCAL_AUTH_BYPASS_ENV_VAR = "DASHBOARD_ALLOW_LOCAL_NO_PASSWORD"
PASSWORD_ENV_VARS = (
    "DASHBOARD_PASSWORD",
    "GARNER_QUANT_DASHBOARD_PASSWORD",
)
AUTH_SECRET_ENV_VAR = "DASHBOARD_AUTH_SECRET"
SESSION_DAYS_ENV_VAR = "DASHBOARD_SESSION_DAYS"
PRODUCTION_ENV_VARS = (
    "AWS_EXECUTION_ENV",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "EB_ENVIRONMENT_NAME",
    "ECS_CONTAINER_METADATA_URI",
    "ECS_CONTAINER_METADATA_URI_V4",
)
ENVIRONMENT_ENV_VARS = (
    "GARNER_QUANT_ENV",
    "DASHBOARD_ENV",
    "APP_ENV",
    "ENVIRONMENT",
    "ENV",
)
PRODUCTION_ENV_VALUES = {"prod", "production", "aws"}


def _truthy_env(name):
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name, default):
    value = os.getenv(name, "")
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _load_env_file():
    if load_dotenv is None:
        return
    try:
        load_dotenv()
    except Exception:
        pass


def _secret_value(key):
    try:
        return st.secrets.get(key)
    except Exception:
        return None


def dashboard_password():
    _load_env_file()

    dashboard_config = _secret_value("dashboard")
    if hasattr(dashboard_config, "get"):
        password = dashboard_config.get("password")
        if password:
            return str(password)

    password = _secret_value("dashboard_password")
    if password:
        return str(password)

    for env_var in PASSWORD_ENV_VARS:
        password = os.getenv(env_var)
        if password:
            return password

    return None


def dashboard_auth_secret(password):
    _load_env_file()
    secret = os.getenv(AUTH_SECRET_ENV_VAR)
    if secret:
        return secret
    return hashlib.sha256(f"dashboard-auth:{password}".encode("utf-8")).hexdigest()


def dashboard_session_days():
    _load_env_file()
    return _int_env(SESSION_DAYS_ENV_VAR, 7)


def is_production_dashboard():
    _load_env_file()

    for env_var in ENVIRONMENT_ENV_VARS:
        value = os.getenv(env_var, "").strip().lower()
        if value in PRODUCTION_ENV_VALUES:
            return True

    return any(os.getenv(env_var) for env_var in PRODUCTION_ENV_VARS)


def allow_local_no_password():
    _load_env_file()
    return _truthy_env(LOCAL_AUTH_BYPASS_ENV_VAR)


def _password_fingerprint(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _b64encode_json(payload):
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode_json(value):
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode((value + padding).encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _sign_token_payload(payload, secret):
    digest = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_auth_token(password, now=None, session_days=None):
    now = int(time.time() if now is None else now)
    session_days = dashboard_session_days() if session_days is None else session_days
    expires_at = now + int(session_days * 24 * 60 * 60)
    payload = _b64encode_json(
        {
            "version": 1,
            "iat": now,
            "exp": expires_at,
            "pwd": _password_fingerprint(password),
        }
    )
    signature = _sign_token_payload(payload, dashboard_auth_secret(password))
    return f"{payload}.{signature}"


def validate_auth_token(token, password, now=None):
    if not token or "." not in str(token):
        return False

    payload, signature = str(token).split(".", 1)
    expected = _sign_token_payload(payload, dashboard_auth_secret(password))
    if not hmac.compare_digest(signature, expected):
        return False

    try:
        data = _b64decode_json(payload)
    except Exception:
        return False

    if data.get("version") != 1:
        return False
    if data.get("pwd") != _password_fingerprint(password):
        return False

    now = int(time.time() if now is None else now)
    try:
        expires_at = int(data.get("exp"))
    except Exception:
        return False
    return now < expires_at


def _password_matches(entered_password, configured_password):
    entered_bytes = (entered_password or "").encode("utf-8")
    configured_bytes = configured_password.encode("utf-8")
    return hmac.compare_digest(entered_bytes, configured_bytes)


def _is_authenticated(password):
    expected_fingerprint = _password_fingerprint(password)
    return (
        bool(st.session_state.get(AUTH_SESSION_KEY))
        and st.session_state.get(AUTH_FINGERPRINT_KEY) == expected_fingerprint
    )


def _set_authenticated(password):
    st.session_state[AUTH_SESSION_KEY] = True
    st.session_state[AUTH_FINGERPRINT_KEY] = _password_fingerprint(password)
    st.session_state[AUTH_PENDING_TOKEN_KEY] = build_auth_token(password)


def _set_authenticated_from_cookie(password):
    st.session_state[AUTH_SESSION_KEY] = True
    st.session_state[AUTH_FINGERPRINT_KEY] = _password_fingerprint(password)


def _cookie_token():
    try:
        return st.context.cookies.get(AUTH_TOKEN_COOKIE)
    except Exception:
        return None


def _cookie_attributes(max_age_seconds=None):
    attributes = ["path=/", "SameSite=Lax"]
    try:
        if st.context.url.startswith("https://"):
            attributes.append("Secure")
    except Exception:
        pass
    if max_age_seconds is not None:
        attributes.append(f"Max-Age={int(max_age_seconds)}")
    return "; ".join(attributes)


def _write_cookie_script(token):
    max_age_seconds = dashboard_session_days() * 24 * 60 * 60
    cookie = (
        f"{AUTH_TOKEN_COOKIE}={token}; "
        + _cookie_attributes(max_age_seconds=max_age_seconds)
    )
    components.html(
        f"""
        <script>
        document.cookie = {json.dumps(cookie)};
        </script>
        """,
        height=0,
    )


def _clear_cookie_script():
    cookie = f"{AUTH_TOKEN_COOKIE}=; " + _cookie_attributes(max_age_seconds=0)
    components.html(
        f"""
        <script>
        document.cookie = {json.dumps(cookie)};
        </script>
        """,
        height=0,
    )


def _flush_pending_cookie_operations():
    token = st.session_state.pop(AUTH_PENDING_TOKEN_KEY, None)
    if token:
        _write_cookie_script(token)

    if st.session_state.pop(AUTH_PENDING_CLEAR_KEY, False):
        _clear_cookie_script()


def _show_development_warning():
    value = os.getenv(DEV_WARNING_ENV_VAR, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def logout_dashboard():
    st.session_state.pop(AUTH_SESSION_KEY, None)
    st.session_state.pop(AUTH_FINGERPRINT_KEY, None)
    st.session_state.pop(AUTH_PENDING_TOKEN_KEY, None)
    st.session_state[AUTH_PENDING_CLEAR_KEY] = True


def _render_logout():
    _flush_pending_cookie_operations()
    with st.sidebar:
        st.caption("Garner Quant")
        if st.button("Logout", key="gq_dashboard_logout"):
            logout_dashboard()
            _flush_pending_cookie_operations()
            st.success("Logged out.")
            st.stop()


def _render_lock_screen(password):
    st.markdown(
        """
        <style>
        .gq-lock {
            max-width: 440px;
            margin: 10vh auto 0 auto;
            padding: 1.5rem;
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 8px;
            background: rgba(255,255,255,0.025);
        }
        .gq-lock h1 {
            margin-bottom: 0.25rem;
        }
        .gq-lock p {
            color: rgba(250,250,250,0.72);
            margin-top: 0;
        }
        </style>
        <div class="gq-lock">
            <h1>Garner Quant</h1>
            <p>Private dashboard access</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("gq_dashboard_login"):
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Unlock", type="primary")

    if submitted:
        if _password_matches(entered_password, password):
            _set_authenticated(password)
            st.rerun()
        st.error("Unable to unlock dashboard.")

    st.stop()


def require_dashboard_login():
    password = dashboard_password()
    if not password:
        if is_production_dashboard() or not allow_local_no_password():
            st.error(
                "Dashboard access is locked because no password is configured. "
                "Set DASHBOARD_PASSWORD before starting the dashboard."
            )
            st.stop()

        if _show_development_warning():
            st.warning(
                "Development mode: dashboard password is not configured. "
                "Set DASHBOARD_PASSWORD in the environment before production use."
            )
        return True

    if _is_authenticated(password):
        _render_logout()
        return True

    token = _cookie_token()
    if validate_auth_token(token, password):
        _set_authenticated_from_cookie(password)
        _render_logout()
        return True

    _render_lock_screen(password)
    return False
