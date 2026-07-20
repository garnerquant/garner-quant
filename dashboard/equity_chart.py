from __future__ import annotations

import altair as alt
import pandas as pd


RECORDED_COLOUR = "#2563EB"
CONTINUITY_COLOUR = "#94A3B8"


def build_equity_curve_layers(chart_data, shared_encoding, tooltip):
    """Build presentation-only layers for recorded and display-filled equity."""
    base = alt.Chart(chart_data)
    continuity = (
        base.mark_line(
            color=CONTINUITY_COLOUR,
            strokeWidth=1.5,
            strokeDash=[4, 5],
            opacity=0.35,
        )
        .encode(**shared_encoding)
    )
    recorded_line = (
        base.transform_filter(alt.datum.is_recorded)
        .mark_line(color=RECORDED_COLOUR, strokeWidth=3)
        .encode(
            **shared_encoding,
            detail=alt.Detail("recorded_run:N"),
            tooltip=tooltip,
        )
    )
    recorded_points = (
        base.transform_filter(alt.datum.is_recorded)
        .mark_point(
            color=RECORDED_COLOUR,
            filled=True,
            size=72,
        )
        .encode(**shared_encoding, tooltip=tooltip)
    )

    recorded_days = chart_data.loc[
        chart_data["is_recorded"].astype(bool), "challenge_day"
    ]
    if recorded_days.empty:
        return continuity + recorded_line + recorded_points

    final_day = int(recorded_days.max())
    final_point = (
        base.transform_filter(
            alt.datum.is_recorded & (alt.datum.challenge_day == final_day)
        )
        .mark_point(
            color=RECORDED_COLOUR,
            filled=True,
            size=145,
            stroke="white",
            strokeWidth=2,
        )
        .encode(**shared_encoding, tooltip=tooltip)
    )
    return continuity + recorded_line + recorded_points + final_point


def build_realised_equity_chart(chart_data, starting_balance):
    """Build the read-only daily realised-equity presentation chart."""
    values = pd.to_numeric(chart_data["realised_equity"], errors="coerce").dropna()
    minimum, maximum = float(values.min()), float(values.max())
    span = maximum - minimum
    padding = max(span * 0.08, abs(float(starting_balance)) * 0.001, 1.0)
    equity_domain = [minimum - padding, maximum + padding]

    x_encoding = alt.X(
        "date:T",
        title="Realisation date",
        axis=alt.Axis(tickCount=6),
    )
    y_encoding = alt.Y(
        "realised_equity:Q",
        title="Realised equity (GBP)",
        axis=alt.Axis(labelExpr="'£' + format(datum.value, ',.2f')"),
        scale=alt.Scale(domain=equity_domain, zero=False),
    )
    tooltip = [
        alt.Tooltip("date:T", title="Date"),
        alt.Tooltip(
            "daily_realised_pnl:Q",
            title="Daily realised P&L (GBP)",
            format=",.2f",
        ),
        alt.Tooltip(
            "cumulative_realised_pnl:Q",
            title="Cumulative realised P&L (GBP)",
            format=",.2f",
        ),
        alt.Tooltip(
            "realised_equity:Q",
            title="Realised equity (GBP)",
            format=",.2f",
        ),
    ]
    base = alt.Chart(chart_data)
    line = base.mark_line(
        interpolate="linear",
        color=RECORDED_COLOUR,
        strokeWidth=3,
    ).encode(x=x_encoding, y=y_encoding, tooltip=tooltip)
    points = base.mark_point(
        color=RECORDED_COLOUR,
        filled=True,
        shape="circle",
        size=75,
        stroke="white",
        strokeWidth=1,
    ).encode(x=x_encoding, y=y_encoding, tooltip=tooltip)
    reference = (
        alt.Chart(pd.DataFrame({"starting_balance": [float(starting_balance)]}))
        .mark_rule(color="#64748B", opacity=0.45, strokeDash=[5, 5], strokeWidth=1.25)
        .encode(y=alt.Y("starting_balance:Q", scale=alt.Scale(domain=equity_domain)))
    )
    return (reference + line + points).properties(height=320)
