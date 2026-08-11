import os
from pathlib import Path

import pytest

from tests.safety_controls import install_safety_controls


@pytest.fixture(autouse=True)
def test_safety_controls(monkeypatch):
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    install_safety_controls(monkeypatch)


@pytest.fixture
def isolated_test_root(tmp_path):
    root = tmp_path.resolve()
    assert root.is_absolute()
    assert not root.is_relative_to(Path(__file__).resolve().parents[1])
    assert not any(root.iterdir())
    return root
