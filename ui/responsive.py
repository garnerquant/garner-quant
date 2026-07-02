import html

import pandas as pd
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
            overflow-x: hidden;
        }

        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(128,128,128,0.22);
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
        }

        div[data-testid="stMetricValue"],
        div[data-testid="stMetricDelta"],
        div[data-testid="stMetricLabel"] p {
            overflow-wrap: anywhere;
        }

        div[data-testid="stDataFrame"] {
            width: 100%;
            max-width: 100%;
            overflow-x: auto;
        }

        div[data-testid="stDataFrame"] canvas,
        div[data-testid="stDataFrame"] iframe {
            max-width: 100%;
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

        .gq-table-mobile {
            display: none;
        }

        .gq-mobile-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 0.9rem;
        }

        .gq-mobile-table th,
        .gq-mobile-table td {
            border-bottom: 1px solid rgba(128,128,128,0.22);
            padding: 0.55rem 0.45rem;
            text-align: left;
            vertical-align: top;
            overflow-wrap: anywhere;
        }

        .gq-mobile-table th {
            color: rgba(250,250,250,0.76);
            font-weight: 700;
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
                width: 100%;
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

            .gq-table-mobile {
                display: block;
                width: 100%;
                overflow-x: hidden;
            }

            div[data-testid="stElementContainer"]:has(.gq-hide-next-on-mobile)
                + div[data-testid="stElementContainer"],
            div.element-container:has(.gq-hide-next-on-mobile)
                + div.element-container {
                display: none;
            }
        }

        @media (min-width: 769px) and (max-width: 1100px) {
            div[data-testid="column"] {
                flex: 1 1 calc(50% - 0.75rem) !important;
                min-width: calc(50% - 0.75rem) !important;
            }

            div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
                gap: 0.75rem;
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


def compact_label(label, max_length=18):
    text = str(label)
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."


def mobile_table_columns(data, columns):
    if not isinstance(data, pd.DataFrame):
        return data

    available = [column for column in columns if column in data.columns]
    if not available:
        return data
    return data[available]


def _mobile_table_html(data, columns, max_rows):
    display = mobile_table_columns(data, columns)
    if not isinstance(display, pd.DataFrame):
        return ""

    if max_rows is not None:
        display = display.head(max_rows)

    header_cells = "".join(
        f"<th>{html.escape(compact_label(column, 22))}</th>"
        for column in display.columns
    )
    body_rows = []
    for _, row in display.iterrows():
        cells = "".join(
            f"<td>{html.escape('' if pd.isna(value) else str(value))}</td>"
            for value in row
        )
        body_rows.append(f"<tr>{cells}</tr>")

    return (
        '<table class="gq-mobile-table">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


def responsive_table(
    data,
    *,
    hide_index=True,
    use_container_width=True,
    mobile_columns=None,
    mobile_max_rows=25,
    **kwargs,
):
    hide_index = kwargs.pop("hide_index", hide_index)
    use_container_width = kwargs.pop("use_container_width", use_container_width)
    width = kwargs.pop("width", "stretch" if use_container_width else "content")

    has_mobile_table = mobile_columns and isinstance(data, pd.DataFrame)
    if has_mobile_table:
        st.markdown(
            (
                '<div class="gq-table-mobile">'
                f"{_mobile_table_html(data, mobile_columns, mobile_max_rows)}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    if has_mobile_table:
        st.markdown(
            '<span class="gq-hide-next-on-mobile"></span>',
            unsafe_allow_html=True,
        )

    result = st.dataframe(
        data,
        hide_index=hide_index,
        width=width,
        **kwargs,
    )
    return result


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
