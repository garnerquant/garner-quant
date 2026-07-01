import json

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


def _scroll_script(key, interval_seconds=None):
    storage_key = json.dumps(f"garner_quant_scroll_{key}")
    timer_key = json.dumps(f"garner_quant_refresh_timer_{key}")
    listener_key = json.dumps(f"garner_quant_scroll_listener_{key}")
    interval_ms = (
        "null"
        if interval_seconds is None
        else str(max(1, int(interval_seconds)) * 1000)
    )

    st.iframe(
        f"""
        <script>
        (function() {{
            try {{
                const parentWindow = window.parent;
                const storageKey = {storage_key};
                const timerKey = {timer_key};
                const listenerKey = {listener_key};
                const intervalMs = {interval_ms};

                function currentScrollY() {{
                    return parentWindow.scrollY ||
                        parentWindow.pageYOffset ||
                        parentWindow.document.documentElement.scrollTop ||
                        parentWindow.document.body.scrollTop ||
                        0;
                }}

                function saveScroll() {{
                    try {{
                        parentWindow.sessionStorage.setItem(
                            storageKey,
                            String(currentScrollY())
                        );
                    }} catch (error) {{}}
                }}

                function restoreScroll() {{
                    try {{
                        const raw = parentWindow.sessionStorage.getItem(storageKey);
                        if (raw === null) {{
                            return;
                        }}
                        const y = parseInt(raw, 10);
                        if (Number.isNaN(y)) {{
                            return;
                        }}
                        parentWindow.requestAnimationFrame(function() {{
                            parentWindow.scrollTo({{ top: y, behavior: "auto" }});
                        }});
                    }} catch (error) {{}}
                }}

                if (parentWindow[listenerKey]) {{
                    parentWindow.removeEventListener(
                        "scroll",
                        parentWindow[listenerKey]
                    );
                }}
                parentWindow[listenerKey] = saveScroll;
                parentWindow.addEventListener(
                    "scroll",
                    parentWindow[listenerKey],
                    {{ passive: true }}
                );
                parentWindow.addEventListener("beforeunload", saveScroll);
                restoreScroll();

                if (parentWindow[timerKey]) {{
                    parentWindow.clearTimeout(parentWindow[timerKey]);
                    parentWindow[timerKey] = null;
                }}

                // Fallback path for environments without streamlit-autorefresh.
                // It must reload the page, but it preserves scroll position when
                // the browser allows component JavaScript to access the parent.
                if (intervalMs !== null) {{
                    parentWindow[timerKey] = parentWindow.setTimeout(function() {{
                        saveScroll();
                        parentWindow.location.reload();
                    }}, intervalMs);
                }}
            }} catch (error) {{
                // Streamlit Cloud/browser sandbox changes can block parent access.
                // In that case auto-refresh still falls back gracefully elsewhere.
            }}
        }})();
        </script>
        """,
        height=1,
        width=1,
    )


def enable_auto_refresh(
    interval_seconds=60,
    key="dashboard_auto_refresh",
    default_enabled=False,
):
    interval_seconds = _valid_interval(interval_seconds, interval_seconds)
    enabled_key = f"{key}_enabled"
    interval_key = f"{key}_interval"
    enabled_control_key = f"{enabled_key}_control"
    interval_control_key = f"{interval_key}_control"
    query_enabled = _query_enabled(enabled_key)
    query_interval = _query_value(interval_key)

    if enabled_key not in st.session_state:
        st.session_state[enabled_key] = (
            bool(default_enabled)
            if query_enabled is None
            else query_enabled
        )
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
            "Enable auto-refresh",
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

    method = "disabled"
    fallback_interval = None
    if enabled:
        method = "streamlit_autorefresh"
        try:
            from streamlit_autorefresh import st_autorefresh

            st_autorefresh(
                interval=interval * 1000,
                key=f"{key}_tick",
            )
        except Exception:
            method = "scroll_preserving_reload_fallback"
            fallback_interval = interval

    _scroll_script(key, interval_seconds=fallback_interval)

    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "method": method,
    }
