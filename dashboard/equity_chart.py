from __future__ import annotations

import altair as alt


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
