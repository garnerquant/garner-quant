import ast
import unittest
from pathlib import Path

from reporting.evidence_labels import evidence_label


class EvidenceLabelTests(unittest.TestCase):
    def test_supported_statuses_are_deterministic_and_safe(self):
        statuses = (
            "legacy_methodologically_invalid",
            "legacy_unverified",
            "paper_observation_unverified",
            "accounting_evidence_not_quantitative_validation",
            "operational_evidence_not_quantitative_validation",
        )
        forbidden = {"validated", "decision_grade", "production_ready", "live_ready"}
        for status in statuses:
            first = evidence_label(status)
            self.assertEqual(first, evidence_label(status))
            self.assertFalse(forbidden.intersection({first.status, first.title, first.warning}))

    def test_legacy_warning_contains_required_caveats(self):
        label = evidence_label("legacy_methodologically_invalid")
        text = f"{label.title} {label.warning}"
        for phrase in (
            "Legacy", "methodologically invalid", "not suitable for investment decisions",
            "present-day/current fundamental data", "paper-trading execution model",
            "remain unverified",
        ):
            self.assertIn(phrase, text)

    def test_other_classifications_are_explicit(self):
        self.assertIn("exploratory", evidence_label("legacy_unverified").title.lower())
        self.assertIn("unverified", evidence_label("legacy_unverified").title.lower())
        self.assertIn("operational observations", evidence_label("paper_observation_unverified").warning)
        self.assertIn("does not validate", evidence_label("accounting_evidence_not_quantitative_validation").warning)

    def test_unknown_status_fails_closed(self):
        label = evidence_label("not-a-real-status")
        self.assertEqual(label.status, "legacy_unverified")
        self.assertIn("unverified", label.title.lower())

    def test_helper_is_ui_independent_and_call_sites_are_presentational(self):
        root = Path(__file__).parents[1]
        tree = ast.parse((root / "reporting/evidence_labels.py").read_text(encoding="utf-8"))
        imported = " ".join(ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
        self.assertNotIn("streamlit", imported.lower())
        for relative in (
            "pages/96_backtest_analytics.py",
            "pages/97_research_intelligence.py",
            "pages/98_research_lab.py",
            "web_dashboard.py",
        ):
            self.assertIn("evidence_label", (root / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
