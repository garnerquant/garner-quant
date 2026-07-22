from __future__ import annotations

import altair as alt


RECORDED_COLOUR = "#2563EB"
CONTINUITY_COLOUR = "#94A3B8"
PERFORMANCE_CHART_HEIGHT = 420
PERFORMANCE_FONT = "sans-serif"
PERFORMANCE_GRID_COLOUR = "rgba(148, 163, 184, 0.20)"
PERFORMANCE_AXIS_COLOUR = "#94A3B8"
PERFORMANCE_LABEL_COLOUR = "#CBD5E1"
PERFORMANCE_TITLE_COLOUR = "#E5E7EB"
PERFORMANCE_MARGIN = 5


def apply_performance_chart_layout(chart):
    """Apply the shared Equity/Drawdown presentation without changing data."""
    return (
        chart.properties(height=PERFORMANCE_CHART_HEIGHT)
        .configure(background="transparent", font=PERFORMANCE_FONT, padding=PERFORMANCE_MARGIN)
        .configure_view(stroke=None, fill="transparent")
        .configure_axis(
            gridColor=PERFORMANCE_GRID_COLOUR,
            domainColor=PERFORMANCE_AXIS_COLOUR,
            tickColor=PERFORMANCE_AXIS_COLOUR,
            labelColor=PERFORMANCE_LABEL_COLOUR,
            titleColor=PERFORMANCE_TITLE_COLOUR,
            labelFont=PERFORMANCE_FONT,
            titleFont=PERFORMANCE_FONT,
            labelFontSize=12,
            titleFontSize=13,
        )
    )


def performance_x_encoding(challenge_days):
    return alt.X(
        "challenge_day:Q",
        title="Challenge day",
        axis=alt.Axis(labelExpr="'Day ' + datum.value"),
        scale=alt.Scale(domain=[0, challenge_days]),
    )


def _performance_line_and_points(base, shared_encoding, tooltip, *, final_day):
    line = base.mark_line(color=RECORDED_COLOUR, strokeWidth=3).encode(
        **shared_encoding, tooltip=tooltip
    )
    points = base.mark_point(
        color=RECORDED_COLOUR, filled=True, size=72
    ).encode(**shared_encoding, tooltip=tooltip)
    latest = (
        base.transform_filter(alt.datum.challenge_day == final_day)
        .mark_point(
            color=RECORDED_COLOUR,
            filled=True,
            size=145,
            stroke="white",
            strokeWidth=2,
        )
        .encode(**shared_encoding, tooltip=tooltip)
    )
    return line + points + latest


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


def build_drawdown_chart(chart_data, challenge_days):
    """Build a Drawdown chart using the Equity Curve visual system."""
    base = alt.Chart(chart_data)
    shared_encoding = {
        "x": performance_x_encoding(challenge_days),
        "y": alt.Y(
            "drawdown_pct:Q",
            title="Drawdown (%)",
            scale=alt.Scale(zero=True),
            axis=alt.Axis(format=".2f"),
        ),
    }
    tooltip = [
        alt.Tooltip("challenge_day_label:N", title="Challenge day"),
        alt.Tooltip("timestamp:T", title="Date", format="%Y-%m-%d"),
        alt.Tooltip("drawdown_pct:Q", title="Drawdown", format=".2f"),
    ]
    final_day = int(chart_data["challenge_day"].max())
    zero_line = (
        alt.Chart({"values": [{"zero": 0}]})
        .mark_rule(color="rgba(148, 163, 184, 0.75)", strokeDash=[5, 5])
        .encode(y="zero:Q")
    )
    return apply_performance_chart_layout(
        zero_line + _performance_line_and_points(
            base, shared_encoding, tooltip, final_day=final_day
        )
    )
