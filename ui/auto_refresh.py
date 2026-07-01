import streamlit as st


INTERVAL_OPTIONS = [15, 30, 60, 120]


def _query_value(name):
    try:
        value = st.query_params.get(name)
    except Exception:
        return None

    if isinstance(value, list):
        return value[0] if value else None
    return value


def _query_enabled(name):
    value = _query_value(name)
    if value is None:
        return None
    return str(value).lower() in {"1", "true", "on", "yes"}


def _write_query_value(name, value):
    try:
        st.query_params[name] = str(value)
    except Exception:
        pass


def _valid_interval(value, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default

    return value if value in INTERVAL_OPTIONS else default


def _meta_refresh(interval_seconds):
    st.markdown(
        f"<meta http-equiv='refresh' content='{int(interval_seconds)}'>",
        unsafe_allow_html=True,
    )


def enable_auto_refresh(interval_seconds=60, key="dashboard_auto_refresh"):
    interval_seconds = _valid_interval(interval_seconds, interval_seconds)
    enabled_key = f"{key}_enabled"
    interval_key = f"{key}_interval"
    enabled_control_key = f"{enabled_key}_control"
    interval_control_key = f"{interval_key}_control"
    query_enabled = _query_enabled(enabled_key)
    query_interval = _query_value(interval_key)

    if enabled_key not in st.session_state:
        st.session_state[enabled_key] = True if query_enabled is None else query_enabled
    if interval_key not in st.session_state:
        st.session_state[interval_key] = _valid_interval(
            query_interval,
            interval_seconds,
        )

    st.session_state[interval_key] = _valid_interval(
        st.session_state[interval_key],
        interval_seconds,
    )
    if enabled_control_key not in st.session_state:
        st.session_state[enabled_control_key] = bool(st.session_state[enabled_key])
    if interval_control_key not in st.session_state:
        st.session_state[interval_control_key] = st.session_state[interval_key]

    with st.sidebar.expander("Auto-refresh", expanded=False):
        enabled = st.checkbox(
            "Auto-refresh",
            key=enabled_control_key,
        )
        interval = st.selectbox(
            "Refresh interval",
            INTERVAL_OPTIONS,
            key=interval_control_key,
            format_func=lambda value: f"{value}s",
        )
        st.session_state[enabled_key] = bool(enabled)
        st.session_state[interval_key] = int(interval)
        status = "ON" if enabled else "OFF"
        st.caption(f"Auto-refresh: {status}")
        if enabled:
            st.caption(f"Every {interval}s")

    enabled = bool(st.session_state[enabled_key])
    interval = int(st.session_state[interval_key])
    _write_query_value(enabled_key, "1" if enabled else "0")
    _write_query_value(interval_key, interval)

    if enabled:
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(
                interval=interval * 1000,
                key=f"{key}_tick",
            )
        except Exception:
            _meta_refresh(interval)

    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "method": "streamlit_autorefresh_or_meta_refresh",
    }
