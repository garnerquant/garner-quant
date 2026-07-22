from __future__ import annotations

import unittest
from pathlib import Path

import altair as alt
import pandas as pd

from dashboard.equity_chart import (
    PERFORMANCE_CHART_HEIGHT,
    RECORDED_COLOUR,
    apply_performance_chart_layout,
    build_drawdown_chart,
    build_equity_curve_layers,
    performance_x_encoding,
)


DATA = pd.DataFrame([
    {"timestamp": "2026-07-01", "date": "2026-07-01", "challenge_day": 0,
     "challenge_day_label": "Day 0", "portfolio_value": 10000, "drawdown_pct": 0,
     "is_recorded": True, "recorded_run": 1},
    {"timestamp": "2026-07-02", "date": "2026-07-02", "challenge_day": 1,
     "challenge_day_label": "Day 1", "portfolio_value": 9900, "drawdown_pct": -1,
     "is_recorded": True, "recorded_run": 1},
])


def marks(value):
    found = []
    if isinstance(value, dict):
        if isinstance(value.get("mark"), dict):
            found.append(value["mark"])
        for item in value.values():
            found.extend(marks(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(marks(item))
    return found


class PerformanceChartStyleTests(unittest.TestCase):
    def drawdown_spec(self):
        return build_drawdown_chart(
            DATA[["timestamp", "challenge_day", "challenge_day_label", "drawdown_pct"]],
            60,
        ).to_dict()

    def equity_spec(self):
        encoding = {
            "x": performance_x_encoding(60),
            "y": alt.Y("portfolio_value:Q", title="Portfolio value", axis=alt.Axis(format=",.2f")),
        }
        chart = build_equity_curve_layers(DATA, encoding, [alt.Tooltip("challenge_day_label:N")])
        return apply_performance_chart_layout(chart).to_dict()

    def test_shared_layout_background_axes_font_height_and_margin(self):
        equity = self.equity_spec(); drawdown = self.drawdown_spec()
        self.assertEqual(drawdown["height"], PERFORMANCE_CHART_HEIGHT)
        self.assertEqual(drawdown["height"], equity["height"])
        self.assertEqual(drawdown["config"], equity["config"])
        self.assertEqual(drawdown["config"]["background"], "transparent")
        self.assertEqual(drawdown["config"]["padding"], 5)

    def test_line_marker_and_latest_point_reuse_equity_blue(self):
        drawdown_marks = marks(self.drawdown_spec())
        equity_marks = marks(self.equity_spec())
        for property_name, expected in (("strokeWidth", 3), ("size", 72), ("size", 145)):
            self.assertTrue(any(mark.get(property_name) == expected and mark.get("color") == RECORDED_COLOUR for mark in drawdown_marks))
            self.assertTrue(any(mark.get(property_name) == expected and mark.get("color") == RECORDED_COLOUR for mark in equity_marks))
        latest = next(mark for mark in drawdown_marks if mark.get("size") == 145)
        self.assertEqual((latest["stroke"], latest["strokeWidth"]), ("white", 2))

    def test_axes_hover_and_full_challenge_domain(self):
        spec = self.drawdown_spec()
        text = str(spec)
        self.assertIn("Drawdown (%)", text)
        self.assertIn("Challenge day", text)
        self.assertIn("Drawdown", text)
        self.assertIn(".2f", text)
        domains = []
        def visit(value):
            if isinstance(value, dict):
                if value.get("field") == "challenge_day" and "scale" in value:
                    domains.append(value["scale"].get("domain"))
                for item in value.values(): visit(item)
            elif isinstance(value, list):
                for item in value: visit(item)
        visit(spec)
        self.assertTrue(domains and all(domain == [0, 60] for domain in domains))

    def test_chart_does_not_fabricate_future_values_or_change_drawdown(self):
        chart = build_drawdown_chart(DATA[["timestamp", "challenge_day", "challenge_day_label", "drawdown_pct"]], 60)
        datasets = chart.to_dict()["datasets"]
        rows = next(rows for rows in datasets.values() if rows and "drawdown_pct" in rows[0])
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["drawdown_pct"] for row in rows], [0, -1])
        self.assertTrue(all(row["drawdown_pct"] <= 0 for row in rows))

    def test_drawdown_spacing_is_scoped_without_changing_chart_render_size(self):
        source = (Path(__file__).resolve().parents[1] / "web_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('.performance-drawdown-heading', source)
        self.assertIn('margin-top: -0.5rem', source)
        self.assertEqual(source.count('st.altair_chart('), 2)
        self.assertEqual(source.count('width="stretch"'), 2)
        self.assertIn('apply_performance_chart_layout(chart)', source)
        self.assertIn('build_drawdown_chart(', source)


if __name__ == "__main__":
    unittest.main()
