import shutil, unittest
from datetime import datetime, timezone
from pathlib import Path

from dashboard.continuous_research_reader import continuous_research_status
from research.continuous_improvement.artifacts import publish_morning_report
from research.continuous_improvement.evidence import build_evidence_snapshot
from research.continuous_improvement.workflow import build_morning_report

ROOT=Path(__file__).resolve().parents[1]; NOW=datetime(2026,7,22,20,tzinfo=timezone.utc)


class ContinuousResearchDashboardTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/".tmp/continuous_research_dashboard"; shutil.rmtree(self.root,ignore_errors=True); self.root.mkdir(parents=True)
    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)
    def test_empty_and_hash_validated_published_states(self):
        self.assertEqual(continuous_research_status(self.root)["status"],"EMPTY")
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW); report=build_morning_report(snapshot,created_at=NOW)
        publish_morning_report(report,self.root)
        status=continuous_research_status(self.root); self.assertEqual(status["status"],"PUBLISHED"); self.assertEqual(status["report"]["content_hash"],report.content_hash)
        path=self.root/"morning_reports"/report.report_id/"morning_report.json"; path.write_text("{}",encoding="utf-8")
        self.assertEqual(continuous_research_status(self.root)["status"],"EMPTY")


if __name__=="__main__": unittest.main()
