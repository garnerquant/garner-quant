from __future__ import annotations

import unittest
from datetime import datetime, timezone

from dashboard.operations_presentation import (
    activity_cards_html, compact_date, compact_time, detail_rows,
    home_source_rows, instrument_status_rows, status_table_html,
    summary_cards_html,
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
        self.assertEqual([row["Status"] for row in rows], ["Reconciled", "Remote", "Fallback", "Unavailable"])
        self.assertEqual([row["Tone"] for row in rows], ["green", "blue", "amber", "red"])

    def test_instrument_status_preserves_outcome_and_reason(self):
        rows = instrument_status_rows({
            "AAPL": {"status": "EXECUTION_BLOCKED", "failure_reason": "mode is monitor_only", "identity": {"bar_close_utc": "2026-07-20T20:00:00+00:00"}},
            "VWRL.L": {"status": "NO_ACTION", "identity": {"bar_close_utc": "2026-07-20T15:30:00+00:00"}},
            "BAD": {"status": "FAILED_FINAL", "failure_reason": "missing_metadata", "identity": {}},
        })
        by_symbol = {row["Instrument"]: row for row in rows}
        self.assertEqual(by_symbol["AAPL"]["Status"], "Execution Disabled")
        self.assertEqual(by_symbol["AAPL"]["Reason"], "Monitor-only mode")
        self.assertEqual(by_symbol["VWRL.L"]["Reason"], "Strategy conditions")
        self.assertEqual(by_symbol["BAD"]["Reason"], "Missing metadata")
        self.assertEqual(by_symbol["AAPL"]["Last Bar"], "20 Jul")

    def test_time_formatting_fails_closed(self):
        self.assertEqual(compact_date("invalid"), "Unavailable")
        self.assertEqual(compact_time(datetime(2026, 7, 22, 16, 1)), "Unavailable")

    def test_status_table_is_accessible_responsive_and_escaped(self):
        markup = status_table_html([{"Source": "<Broker>", "Status": "Reconciled", "Tone": "green", "Last Refresh": "17:01"}],
                                   ("Source", "Status", "Last Refresh"), caption="Home data sources")
        self.assertIn('<th scope="col">Status</th>', markup)
        self.assertIn('data-label="Last Refresh"', markup)
        self.assertIn('aria-label="Status: Reconciled"', markup)
        self.assertIn("&lt;Broker&gt;", markup); self.assertNotIn("<Broker>", markup)

    def test_summary_cards_include_text_labels_and_tooltips(self):
        markup = summary_cards_html([{"label": "Evidence Coverage", "value": "0%", "tone": "amber", "help": "Verified evidence only."}], aria_label="Accounting status summary")
        self.assertIn("Evidence Coverage", markup); self.assertIn("0%", markup)
        self.assertIn('title="Verified evidence only."', markup); self.assertIn('tabindex="0"', markup)
        self.assertIn("ops-card-amber", markup)

    def test_activity_cards_preserve_event_and_timestamp(self):
        markup = activity_cards_html([{"icon": "●", "title": "Runtime", "event": "Strategy scan skipped", "timestamp": "Today at 17:01"}])
        self.assertIn("Runtime", markup); self.assertIn("Strategy scan skipped", markup)
        self.assertIn("Today at 17:01", markup); self.assertIn("aria-hidden", markup)

    def test_detail_rows_preserve_information_without_dense_mapping(self):
        self.assertEqual(detail_rows({"status": "ACTIVE", "error": None}, (("status", "Status"), ("error", "Diagnostic"))),
                         [{"Item": "Status", "Value": "ACTIVE"}, {"Item": "Diagnostic", "Value": "Unavailable"}])


if __name__ == "__main__": unittest.main()
