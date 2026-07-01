import streamlit as st


MOBILE_BREAKPOINT_PX = 768


def is_mobile():
    """Best-effort hook for future viewport-aware components.

    Streamlit does not expose viewport width server-side by default, so current
    responsive behavior is implemented with CSS media queries.
    """
    return False


def apply_responsive_styles():
    st.markdown(
        """
        <style>
        :root {
            --gq-mobile-breakpoint: 768px;
        }

        .block-container {
            max-width: 1280px;
            padding-top: 2rem;
            padding-left: 1.25rem;
            padding-right: 1.25rem;
        }

        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(128,128,128,0.22);
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
        }

        div[data-testid="stDataFrame"] {
            width: 100%;
            overflow-x: auto;
        }

        div.stButton > button,
        div[data-testid="stDownloadButton"] > button {
            min-height: 2.6rem;
            border-radius: 8px;
        }

        .gq-responsive-card {
            border: 1px solid rgba(128,128,128,0.25);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 0.85rem;
            background: rgba(255,255,255,0.025);
        }

        .gq-responsive-section {
            margin-top: 1.25rem;
            margin-bottom: 1.25rem;
        }

        @media (max-width: 768px) {
            .block-container {
                padding-top: 1rem;
                padding-left: 0.75rem;
                padding-right: 0.75rem;
            }

            div[data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }

            div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
                gap: 0.75rem;
            }

            div[data-testid="stMetric"] {
                padding: 0.9rem;
                min-height: 5rem;
            }

            div[data-testid="stMetricLabel"] p {
                font-size: 0.9rem;
            }

            div[data-testid="stMetricValue"] {
                font-size: 1.35rem;
                line-height: 1.25;
            }

            div.stButton > button,
            div[data-testid="stDownloadButton"] > button {
                width: 100%;
                min-height: 3rem;
                font-size: 1rem;
            }

            .stTabs [data-baseweb="tab-list"] {
                gap: 0.25rem;
                overflow-x: auto;
            }

            .stTabs [data-baseweb="tab"] {
                min-width: max-content;
            }

            .gq-desktop-only {
                display: none !important;
            }

            .gq-responsive-card {
                padding: 0.9rem;
            }
        }

        @media (min-width: 769px) {
            .gq-mobile-only {
                display: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def responsive_columns(count, *, mobile_count=1, gap="small"):
    """Return Streamlit columns that collapse via shared CSS on mobile."""
    if isinstance(count, int):
        return st.columns(count, gap=gap)

    return st.columns(count, gap=gap)


def responsive_metric_grid(metrics, columns=4):
    cols = responsive_columns(columns)

    for index, metric in enumerate(metrics):
        column = cols[index % len(cols)]
        with column:
            st.metric(
                metric.get("label", ""),
                metric.get("value", ""),
                metric.get("delta"),
            )


def responsive_table(data, *, hide_index=True, use_container_width=True, **kwargs):
    hide_index = kwargs.pop("hide_index", hide_index)
    use_container_width = kwargs.pop("use_container_width", use_container_width)
    width = kwargs.pop("width", "stretch" if use_container_width else "content")

    return st.dataframe(
        data,
        hide_index=hide_index,
        width=width,
        **kwargs,
    )


def responsive_card(title=None):
    container = st.container(border=True)

    if title:
        with container:
            st.markdown(f"**{title}**")

    return container


def responsive_section(title=None, *, divider=True):
    if divider:
        st.divider()

    if title:
        st.subheader(title)

    return st.container()
