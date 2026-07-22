from __future__ import annotations

import unittest
from datetime import datetime, timezone

from dashboard.operations_presentation import (
    activity_cards_html, badge_color, compact_date, compact_time, detail_rows,
    data_health_summary, home_source_rows, instrument_status_rows,
    operational_summary_html, status_table_html, status_meta,
    summary_cards_html, trading_status_summary,
)


class OperationalDashboardPresentationTests(unittest.TestCase):
    def test_home_sources_are_ordered_and_human_readable(self):
        timestamp = datetime(2026, 7, 22, 16, 1, tzinfo=timezone.utc)
        rows = home_source_rows({
            "broker_account": {"source": "local CSV (reconciled)", "local_timestamp": timestamp},
            "trade_journal": {"source": "Supabase", "remote_timestamp": timestamp},
            "holdings": {"source": "local CSV fallback", "local_timestamp": timestamp},
            "paper_30_day_tracker": {"source": "unavailable"},
        })
        self.assertEqual([row["Source"] for row in rows], ["Broker", "Trades", "Holdings", "Tracker"])
        self.assertEqual([row["Status"] for row in rows], ["Reconciled", "Remote", "Fallback", "Not available"])
        self.assertEqual([row["Tone"] for row in rows], ["green", "blue", "amber", "red"])

    def test_instrument_status_preserves_outcome_and_reason(self):
        rows = instrument_status_rows({
            "AAPL": {"status": "EXECUTION_BLOCKED", "failure_reason": "mode is monitor_only", "identity": {"bar_close_utc": "2026-07-20T20:00:00+00:00"}},
            "VWRL.L": {"status": "NO_ACTION", "identity": {"bar_close_utc": "2026-07-20T15:30:00+00:00"}},
            "BAD": {"status": "FAILED_FINAL", "failure_reason": "missing_metadata", "identity": {}},
        })
        by_symbol = {row["Instrument"]: row for row in rows}
        self.assertEqual(by_symbol["AAPL"]["Status"], "Execution disabled")
        self.assertEqual(by_symbol["AAPL"]["Tone"], "grey")
        self.assertEqual(by_symbol["AAPL"]["Reason"], "Monitor-only mode")
        self.assertEqual(by_symbol["VWRL.L"]["Reason"], "Strategy conditions")
        self.assertEqual(by_symbol["BAD"]["Reason"], "Missing metadata")
        self.assertEqual(by_symbol["AAPL"]["Last Bar"], "20 Jul")

    def test_time_formatting_fails_closed(self):
        self.assertEqual(compact_date("invalid"), "Not available")
        self.assertEqual(compact_time(datetime(2026, 7, 22, 16, 1)), "Not available")

    def test_status_table_is_accessible_responsive_and_escaped(self):
        markup = status_table_html([{"Source": "<Broker>", "Status": "Reconciled", "Tone": "green", "Tooltip": "This source agrees with the authoritative local report.", "Last Refresh": "17:01"}],
                                   ("Source", "Status", "Last Refresh"), caption="Home data sources")
        self.assertIn('<th scope="col">Status</th>', markup)
        self.assertIn('data-label="Last Refresh"', markup)
        self.assertIn('aria-label="Status: Reconciled.', markup)
        self.assertIn('tabindex="0"', markup); self.assertIn('title="This source agrees', markup)
        self.assertIn("&lt;Broker&gt;", markup); self.assertNotIn("<Broker>", markup)

    def test_summary_cards_include_text_labels_and_tooltips(self):
        markup = summary_cards_html([{"label": "Evidence Coverage", "value": "0%", "context": "Verified history", "tone": "amber", "help": "Verified evidence only."}], aria_label="Accounting status summary")
        self.assertIn("Evidence Coverage", markup); self.assertIn("0%", markup)
        self.assertIn('title="Verified evidence only."', markup); self.assertIn('tabindex="0"', markup)
        self.assertIn("ops-card-amber", markup)
        self.assertIn("Verified history", markup)

    def test_summary_cards_preserve_numeric_zero_and_fail_closed_when_absent(self):
        markup = summary_cards_html([
            {"label": "Critical Gaps", "value": 0, "tone": "green"},
            {"label": "Pending Reviews", "value": None, "tone": "grey"},
        ], aria_label="Accounting status summary")
        self.assertIn(">0<", markup)
        self.assertIn("Not available", markup)
        self.assertNotIn("Unavailable", markup)

    def test_semantic_status_colours_distinguish_inactive_and_faults(self):
        self.assertEqual(status_meta("EXECUTION_BLOCKED")[:2], ("Execution disabled", "grey"))
        self.assertEqual(status_meta("CONFLICT")[:2], ("Conflict", "red"))
        self.assertEqual(status_meta("ERROR")[:2], ("Problem", "red"))
        self.assertEqual(status_meta("NO_ACTION")[:2], ("No action", "blue"))
        self.assertEqual(badge_color("amber"), "orange")

    def test_activity_cards_preserve_event_and_timestamp(self):
        markup = activity_cards_html([{"icon": "●", "title": "Runtime", "event": "Strategy scan skipped", "context": "Monitor-only protection", "timestamp": "Today at 17:01", "tone": "grey"}])
        self.assertIn("Runtime", markup); self.assertIn("Strategy scan skipped", markup)
        self.assertIn("Today at 17:01", markup); self.assertIn("aria-hidden", markup)
        self.assertIn("Monitor-only protection", markup); self.assertIn("ops-card-grey", markup)

    def test_detail_rows_preserve_information_without_dense_mapping(self):
        self.assertEqual(detail_rows({"status": "ACTIVE", "error": None}, (("status", "Status"), ("error", "Diagnostic"))),
                         [{"Item": "Status", "Value": "ACTIVE"}, {"Item": "Diagnostic", "Value": "Not available"}])

    def test_raw_scheduler_code_is_not_exposed_in_rendered_table(self):
        rows = instrument_status_rows({"AAPL": {"status": "EXECUTION_BLOCKED", "failure_reason": "mode is monitor_only", "identity": {}}})
        markup = status_table_html(rows, ("Instrument", "Status", "Reason", "Last Bar"), caption="Per-instrument status")
        self.assertNotIn("EXECUTION_BLOCKED", markup)
        self.assertIn("Execution disabled", markup); self.assertIn("Monitor-only mode", markup)

    def test_home_summary_answers_status_and_action_accessibly(self):
        markup = operational_summary_html(
            "System Status", "Healthy", "Runtime running, data current, and monitoring only.",
            (("Trading", "Monitoring only"), ("Action", "No action required")),
            tone="green", help_text="System health summary.",
        )
        self.assertIn("System Status", markup); self.assertIn("Healthy", markup)
        self.assertIn("No action required", markup); self.assertIn("ops-card-green", markup)
        self.assertIn('tabindex="0"', markup); self.assertIn('aria-label="System Status: Healthy.', markup)

    def test_data_health_summary_uses_existing_source_rows(self):
        rows = [{"Status": "Reconciled", "Last Refresh": "18:01"}, {"Status": "Reconciled", "Last Refresh": "18:03"}]
        summary = data_health_summary(rows)
        self.assertEqual(summary["status"], "All sources reconciled")
        self.assertEqual(summary["healthy"], "2 / 2 healthy")
        self.assertEqual(summary["last_updated"], "18:03")

    def test_trading_summary_counts_existing_presentation_statuses(self):
        summary = trading_status_summary([
            {"Status": "Execution disabled", "Tone": "grey"},
            {"Status": "Execution disabled", "Tone": "grey"},
            {"Status": "No action", "Tone": "blue"},
            {"Status": "Failed", "Tone": "red"},
        ])
        self.assertEqual(summary, {"status": "Monitor-only", "tone": "red", "monitored": 4, "waiting": 2, "no_action": 1, "errors": 1})


if __name__ == "__main__": unittest.main()
