from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

import pandas as pd

from dashboard.research_report_reader import ResearchReportBundle
from dashboard.research_status_reader import read_research_pipeline_status, research_report_overview

ROOT = Path(__file__).resolve().parents[1]


class ResearchDashboardPresentationTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".tmp" / "research_dashboard_presentation"
        shutil.rmtree(self.root, ignore_errors=True); self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_report_overview_uses_only_published_fields(self):
        candidates = pd.DataFrame([
            {"group_value": "Candidate", "horizon_days": 5, "observations": 12},
            {"group_value": "Candidate", "horizon_days": 20, "observations": 9},
            {"group_value": "Not Candidate", "horizon_days": 5, "observations": 88},
        ])
        bundle = ResearchReportBundle("report-1", self.root, {
            "created_at": "2026-07-22T12:00:00+00:00", "status": "complete",
            "source_scanner_generations": ["g1", "g2"],
        }, {"observation_count": 100, "generation_count": 2}, {"candidate_report.csv": candidates})
        result = research_report_overview(bundle)
        self.assertEqual(result["universe_analysed"], 100)
        self.assertEqual(result["candidate_count"], 12)
        self.assertIsNone(result["high_conviction_count"])
        self.assertIn("100 observations", result["summary"])

    def test_pipeline_absence_is_unavailable_not_inferred_idle(self):
        result = read_research_pipeline_status(self.root / "absent")
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertIsNone(result.last_successful_run)
        self.assertNotEqual(result.status, "IDLE")

    def test_pipeline_uses_explicit_manifest_statuses(self):
        generations = self.root / "generations"; generations.mkdir()
        rows = [
            ("success", "complete", "2026-07-20T12:00:00+00:00"),
            ("failure", "failed", "2026-07-21T12:00:00+00:00"),
            ("current", "running", "2026-07-22T12:00:00+00:00"),
        ]
        for name, status, created in rows:
            path = generations / name; path.mkdir()
            (path / "research_manifest.json").write_text(json.dumps({
                "status": status, "created_at": created, "report_id": name,
            }), encoding="utf-8")
        result = read_research_pipeline_status(self.root)
        self.assertEqual(result.status, "RUNNING")
        self.assertEqual(result.last_successful_run, rows[0][2])
        self.assertEqual(result.last_failed_run, rows[1][2])
        self.assertEqual(result.report_id, "success")

    def test_pages_have_complete_plain_english_empty_states(self):
        intelligence = (ROOT / "pages/97_research_intelligence.py").read_text(encoding="utf-8")
        lab = (ROOT / "pages/98_research_lab.py").read_text(encoding="utf-8")
        for text in ("Research Status", "No published research available", "When research becomes available",
                     "Latest report", "Candidate opportunities", "Next step"):
            self.assertIn(text, intelligence)
        for text in ("Research Pipeline", "Purpose", "Current Pipeline Status", "Last Successful Run",
                     "Last Failed Run", "Last Publication", "Status unavailable", "Next step"):
            self.assertIn(text, lab)
        self.assertNotIn("No completed immutable research report", intelligence)
        self.assertNotIn("Research runs are produced outside Streamlit", lab)

    def test_changes_are_presentation_only(self):
        reader = (ROOT / "dashboard/research_status_reader.py").read_text(encoding="utf-8")
        for token in ("write_text(", "write_bytes(", "to_csv(", "publish_research_reports",
                      "run_scanner_research", "FeatureGenerationStore", "os.replace"):
            self.assertNotIn(token, reader)
        for page in ("97_research_intelligence.py", "98_research_lab.py"):
            source = (ROOT / "pages" / page).read_text(encoding="utf-8")
            for token in ("write_text(", "write_bytes(", "to_csv(", "publish_research_reports", "run_scanner_research"):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
