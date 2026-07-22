from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.continuous_improvement.analysis import analyse_patterns, analysis_catalogue
from research.continuous_improvement.evidence import build_evidence_snapshot

ROOT = Path(__file__).resolve().parents[1]; NOW = datetime(2026, 7, 22, 20, tzinfo=timezone.utc)


class ContinuousResearchAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT/".tmp/continuous_research_analysis"; shutil.rmtree(self.root, ignore_errors=True); (self.root/"data").mkdir(parents=True)
        rows = ["symbol,open_time,close_time,pnl_pct,strategy,close_reason,entry_event_id,exit_event_id"]
        for index in range(24):
            strategy = "Alpha" if index < 12 else "Control"; outcome = 4 + index/100 if index < 12 else -1-index/100
            reason = "TAKE PROFIT" if index % 2 else "SIGNAL EXIT"
            rows.append(f"S{index%4},2026-01-{index%9+1:02d}T10:00:00+00:00,2026-01-{index%9+2:02d}T10:00:00+00:00,{outcome},{strategy},{reason},b{index},s{index}")
        (self.root/"trade_audit_trail.csv").write_text("\n".join(rows)+"\n", encoding="utf-8")

    def tearDown(self): shutil.rmtree(self.root, ignore_errors=True)

    def test_pattern_analysis_is_deterministic_adjusted_and_noncausal(self):
        snapshot = build_evidence_snapshot(self.root, cutoff=NOW, created_at=NOW)
        one = analyse_patterns(snapshot, generated_at=NOW); two = analyse_patterns(snapshot, generated_at=NOW)
        self.assertEqual(one, two); observations, unsupported, attempted = one
        self.assertGreater(attempted, 0); self.assertTrue(observations)
        self.assertTrue(all(item.attempted_comparisons == attempted for item in observations))
        self.assertTrue(any(item.adjusted_significance is not None for item in observations))
        self.assertTrue(all("associated with" in item.description for item in observations))
        self.assertTrue(all("caused" not in item.description and "proves" not in item.description for item in observations))
        self.assertTrue(any("counterfactual" in value for value in unsupported))

    def test_catalogue_declares_controls_samples_and_unavailable_analyses(self):
        catalogue = analysis_catalogue(); self.assertEqual(len(catalogue), 10)
        self.assertTrue(all(item.feature and item.grouping and item.control and item.minimum_group_sample > 0 for item in catalogue))
        self.assertTrue(any(not item.supported and item.unavailable_reason for item in catalogue))


if __name__ == "__main__": unittest.main()
