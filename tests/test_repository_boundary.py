"""Repository boundary checks for generated paper/release artifacts."""

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git_check_ignore(paths: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        input="\n".join(paths) + "\n",
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    ignored = set(result.stdout.strip().splitlines())
    return {path for path in ignored if path}


def test_generated_submission_artifacts_are_ignored():
    local_artifacts = [
        "quantarena-supp.zip",
        "main.pdf",
        "croissant_metadata.json",
        "release_data/all_metrics.csv",
        "release-data/all_trades.csv",
        "submission/openreview-upload.pdf",
        "supplementary/final-figures.zip",
        "paper_build/main.aux",
        "artifacts/backtest-run/metrics.csv",
        "latex/main.tex",
        "reports/run-summary.md",
        "experiments/live-run/output.json",
        "data/cache/prices.csv",
    ]

    assert _git_check_ignore(local_artifacts) == set(local_artifacts)


def test_source_and_documentation_paths_remain_trackable():
    source_paths = [
        "README.md",
        "pyproject.toml",
        "backtest/metrics.py",
        "quantarena/cli.py",
        "quantarena/artifacts.py",
        "deepfund/src/config/fundamental_value.yaml",
        "docs/DEVELOPMENT.md",
        "tests/test_backtest_metrics.py",
    ]

    assert _git_check_ignore(source_paths) == set()
