"""Adversarial cross-module determinism and publication-boundary checks."""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.point_in_time import UniverseMembership
from research.validated_pipeline import assemble_validated_research, publish_bundle, verify_publication
from tests.test_validated_research_pipeline import dataset, membership, kwargs


def test_repeated_validated_bundle_and_publication_are_byte_identical(tmp_path):
    first = assemble_validated_research(**kwargs())
    second = assemble_validated_research(**kwargs())
    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()
    root = tmp_path / "isolated_test_root"
    namespace = publish_bundle(first, root)
    assert publish_bundle(second, root) == namespace
    assert verify_publication(namespace)


def test_publication_detects_tampering_missing_and_unexpected_files(tmp_path):
    namespace = publish_bundle(assemble_validated_research(**kwargs()), tmp_path / "isolated_test_root")
    (namespace / "unexpected.json").write_text("{}", encoding="utf-8")
    assert not verify_publication(namespace)
    (namespace / "unexpected.json").unlink()
    (namespace / "content_manifest.json").unlink()
    assert not verify_publication(namespace)


def test_publication_rejects_conflict_and_repository_root(tmp_path):
    root = tmp_path / "isolated_test_root"
    bundle = assemble_validated_research(**kwargs())
    namespace = publish_bundle(bundle, root)
    (namespace / "bundle.json").write_bytes(b"conflict")
    with pytest.raises(ValueError): publish_bundle(bundle, root)
    with pytest.raises(ValueError): publish_bundle(bundle, ".")


def test_research_modules_are_production_isolated_and_do_not_use_legacy_paths():
    root = Path(__file__).parents[1]
    modules = ["research/returns.py", "research/corporate_actions.py", "research/execution_model.py", "research/portfolio_simulation.py", "research/validated_pipeline.py"]
    for relative in modules:
        source = (root / relative).read_text(encoding="utf-8")
        assert "main_v2" not in source and "execution.portfolio_manager" not in source and "backtest.engine" not in source
        assert "strategy.portfolio" not in source and "data.fundamentals" not in source and "yfinance" not in source


def test_legacy_result_names_are_not_written_by_publication(tmp_path):
    namespace = publish_bundle(assemble_validated_research(**kwargs()), tmp_path / "isolated_test_root")
    names = {path.name for path in namespace.iterdir()}
    assert names.isdisjoint({"trade_log.csv", "fundamental_scores.csv", "portfolio_v2.csv", "holdings_report.csv", "paper_30_day_tracker.csv"})
