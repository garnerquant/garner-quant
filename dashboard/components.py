import streamlit as st


def inject_mobile_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.2rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 900px;
        }

        div[data-testid="stAlert"] {
            border-radius: 16px;
        }

        .status-card {
            background: linear-gradient(135deg, #123d26, #0f2d20);
            border: 1px solid #2d7a46;
            border-radius: 16px;
            padding: 14px 16px;
            margin-bottom: 24px;
            color: #6df58d;
            font-size: 16px;
        }

        .app-card {
            background: #111827;
            border: 1px solid #30363d;
            border-radius: 18px;
            padding: 18px;
            margin-bottom: 18px;
        }

        .metric-card {
            background: #0f172a;
            border: 1px solid #30363d;
            border-radius: 14px;
            padding: 14px;
            margin-bottom: 10px;
        }

        .metric-label {
            color: #9ca3af;
            font-size: 14px;
            margin-bottom: 6px;
        }

        .metric-value {
            color: #ffffff;
            font-size: 22px;
            font-weight: 800;
        }

        .green {
            color: #6df58d;
        }

        div.stButton > button {
            height: 86px;
            border-radius: 16px;
            border: 1px solid #30363d;
            background: #111827;
            color: white;
            font-size: 15px;
        }

        div.stButton > button:hover {
            border-color: #4ade80;
            color: #6df58d;
        }

        @media (max-width: 600px) {
            h1 {
                font-size: 42px !important;
            }

            h2 {
                font-size: 28px !important;
            }

            div[data-testid="column"] {
                min-width: 0 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def navigation():
    if "page" not in st.session_state:
        st.session_state.page = "Home"

    nav_items = [
        ("Home", "🏠"),
        ("Holdings", "💼"),
        ("Journal", "📖"),
        ("Audit", "🔍"),
        ("Performance", "📈"),
    ]

    cols = st.columns(5)

    for col, (name, icon) in zip(cols, nav_items):
        with col:
            label = f"{icon}\n\n{name}"
            if st.button(label, key=f"nav_{name}", use_container_width=True):
                st.session_state.page = name

    return st.session_state.page


def status_card(last_updated):
    st.markdown(
        f"""
        <div class="status-card">
            <b>✅ Live data connected</b><br>
            Last updated: {last_updated}
        </div>
        """,
        unsafe_allow_html=True
    )


def app_card_start(title):
    st.markdown(
        f"""
        <div class="app-card">
            <h3>{title}</h3>
        """,
        unsafe_allow_html=True
    )


def app_card_end():
    st.markdown("</div>", unsafe_allow_html=True)


def metric_card(label, value, green=False):
    color_class = "green" if green else ""

    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value {color_class}">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )