import hashlib
import hmac
import os

import streamlit as st

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


AUTH_SESSION_KEY = "gq_dashboard_authenticated"
AUTH_FINGERPRINT_KEY = "gq_dashboard_auth_fingerprint"
DEV_WARNING_ENV_VAR = "GARNER_QUANT_SHOW_AUTH_DEV_WARNING"
LOCAL_AUTH_BYPASS_ENV_VAR = "DASHBOARD_ALLOW_LOCAL_NO_PASSWORD"
PASSWORD_ENV_VARS = (
    "DASHBOARD_PASSWORD",
    "GARNER_QUANT_DASHBOARD_PASSWORD",
)
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


def _show_development_warning():
    value = os.getenv(DEV_WARNING_ENV_VAR, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def logout_dashboard():
    st.session_state.pop(AUTH_SESSION_KEY, None)
    st.session_state.pop(AUTH_FINGERPRINT_KEY, None)


def _render_logout():
    with st.sidebar:
        st.caption("Garner Quant")
        if st.button("Logout", key="gq_dashboard_logout"):
            logout_dashboard()
            st.rerun()


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

    _render_lock_screen(password)
    return False
