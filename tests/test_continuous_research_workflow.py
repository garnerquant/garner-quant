from __future__ import annotations

import shutil
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

from research.continuous_improvement.artifacts import load_latest_report_payload, publish_morning_report
from research.continuous_improvement.evidence import build_evidence_snapshot
from research.continuous_improvement.workflow import build_morning_report, transition_hypothesis

ROOT=Path(__file__).resolve().parents[1]; NOW=datetime(2026,7,22,20,tzinfo=timezone.utc)


class ContinuousResearchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/".tmp/continuous_research_workflow"; shutil.rmtree(self.root,ignore_errors=True); self.root.mkdir(parents=True)
        rows=["symbol,open_time,close_time,pnl_pct,strategy,close_reason,entry_event_id,exit_event_id"]
        for i in range(24):
            strategy="Alpha" if i<12 else "Control"; pnl=3+i/100 if i<12 else -2-i/100
            open_day=i%9+1; close_day=open_day+(1 if i<12 else 5)
            rows.append(f"S{i%5},2026-01-{open_day:02d}T10:00:00+00:00,2026-01-{close_day:02d}T10:00:00+00:00,{pnl},{strategy},SIGNAL EXIT,b{i},s{i}")
        (self.root/"trade_audit_trail.csv").write_text("\n".join(rows)+"\n",encoding="utf-8")

    def tearDown(self): shutil.rmtree(self.root,ignore_errors=True)

    def test_hypotheses_are_ranked_falsifiable_and_tasks_require_humans(self):
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW); report=build_morning_report(snapshot,created_at=NOW)
        self.assertLessEqual(len(report.hypotheses),3); self.assertLessEqual(len(report.suggested_tasks),3)
        self.assertTrue(report.hypotheses)
        scores=[int(item.priority_score) for item in report.hypotheses]; self.assertEqual(scores,sorted(scores,reverse=True))
        self.assertTrue(all(item.falsification_condition.startswith("Reject if") for item in report.hypotheses))
        self.assertTrue(all(item.lifecycle_status=="OBSERVED" for item in report.hypotheses))
        self.assertTrue(all(item.status=="PROPOSED" and any("Manual approval" in rule for rule in item.safety_constraints) for item in report.suggested_tasks))
        holding = [item for item in report.hypotheses if "days" in item.title]
        self.assertTrue(holding and all(item.proposed_experiment_type == "exit_rule_comparison" and "time-based exit" in item.hypothesis_statement for item in holding))
        successor=transition_hypothesis(report.hypotheses[0],"TRIAGED",created_at=NOW.replace(hour=21))
        self.assertEqual(successor.predecessor_id,report.hypotheses[0].hypothesis_id); self.assertNotEqual(successor.hypothesis_id,report.hypotheses[0].hypothesis_id)
        with self.assertRaises(FrozenInstanceError): report.report_id="changed"

    def test_morning_report_is_immutable_hash_bound_and_reproducible(self):
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW); first=build_morning_report(snapshot,created_at=NOW); second=build_morning_report(snapshot,created_at=NOW)
        self.assertEqual(first,second); self.assertEqual(first.content_hash,second.content_hash)
        path=publish_morning_report(first,self.root/"published"); self.assertTrue(path.is_dir())
        payload=load_latest_report_payload(self.root/"published"); self.assertEqual(payload["report_id"],first.report_id)
        with self.assertRaises(FileExistsError): publish_morning_report(first,self.root/"published")

    def test_insufficient_evidence_produces_valid_no_ideas_report(self):
        (self.root/"trade_audit_trail.csv").write_text("symbol,open_time,close_time,pnl_pct,strategy\nAAA,2026-01-01T00:00:00+00:00,2026-01-02T00:00:00+00:00,1,Alpha\n",encoding="utf-8")
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW); report=build_morning_report(snapshot,created_at=NOW)
        self.assertEqual(report.observations,()); self.assertEqual(report.hypotheses,()); self.assertEqual(report.suggested_tasks,())
        self.assertEqual(report.executive_summary,"No sufficiently robust new research hypotheses were identified.")

    def test_successor_report_binds_predecessor_without_mutation(self):
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW)
        first=build_morning_report(snapshot,created_at=NOW)
        successor_snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW.replace(minute=1),predecessor_id=snapshot.snapshot_id)
        second=build_morning_report(successor_snapshot,created_at=NOW.replace(minute=1),predecessor_id=first.report_id)
        self.assertEqual(second.predecessor_id,first.report_id); self.assertEqual(successor_snapshot.predecessor_id,snapshot.snapshot_id)
        self.assertNotEqual(second.report_id,first.report_id)

    def test_existing_hypotheses_are_remembered_and_not_requeued(self):
        snapshot=build_evidence_snapshot(self.root,cutoff=NOW,created_at=NOW)
        first=build_morning_report(snapshot,created_at=NOW)
        second=build_morning_report(snapshot,created_at=NOW.replace(minute=1),
                                    predecessor_id=first.report_id,
                                    prior_hypotheses=tuple({"title": item.title} for item in first.hypotheses))
        self.assertTrue(second.hypotheses)
        prior_titles={item.title for item in first.hypotheses}
        repeated=[item for item in second.hypotheses if item.title in prior_titles]
        self.assertTrue(repeated)
        self.assertTrue(all(item.duplication_status == "DUPLICATE" for item in repeated))
        self.assertTrue(all(task.title not in prior_titles for task in second.suggested_tasks))
        self.assertTrue(all(item.observation_period == ("2026-01-01", "2026-01-14") for item in second.observations))


if __name__=="__main__": unittest.main()
