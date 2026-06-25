import streamlit as st


def page_header(title, subtitle=None):
    st.title(title)

    if subtitle:
        st.caption(subtitle)


def kpi_card(label, value):
    st.metric(label, value)


def navigation():
    home, holdings, journal, audit, performance = st.columns(5)

    if "page" not in st.session_state:
        st.session_state.page = "Home"

    if home.button("🏠"):
        st.session_state.page = "Home"

    if holdings.button("💼"):
        st.session_state.page = "Holdings"

    if journal.button("📖"):
        st.session_state.page = "Journal"

    if audit.button("🔍"):
        st.session_state.page = "Audit"

    if performance.button("📈"):
        st.session_state.page = "Performance"

    return st.session_state.page