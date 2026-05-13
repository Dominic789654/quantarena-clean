"""Dependency contract tests for fresh installs."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _pyproject() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_default_dependencies_keep_backtest_reports_complete_without_ml_stack():
    dependencies = set(_pyproject()["project"]["dependencies"])

    assert "matplotlib" in dependencies
    assert "ddgs" in dependencies
    assert "baidusearch" in dependencies
    assert "pycountry" in dependencies
    assert "rank-bm25" in dependencies
    assert "markdown" in dependencies
    assert "torch" not in dependencies
    assert "transformers" not in dependencies
    assert "sentence-transformers" not in dependencies


def test_ml_extra_contains_heavy_predictor_dependencies():
    optional = _pyproject()["project"]["optional-dependencies"]

    assert {"torch", "transformers", "sentence-transformers"}.issubset(set(optional["ml"]))
