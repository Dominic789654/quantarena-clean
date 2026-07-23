"""Coverage for run_full_pipeline's --skip-deepear/--skip-deepfund branches.

Added by the extract-run-mode-handlers-deepear-deepfund-pipeline change
(docs/refactor_program_plan.md Phase 2, step 6 of 8): before this
change, run_full_pipeline had zero test coverage of any kind -- neither
the skip flags nor the continue-on-error propagation logic were
exercised anywhere in the suite.

run_full_pipeline now lives in runner.modes.pipeline and calls
run_deepear/run_deepfund via plain intra-package imports (no test
anywhere monkeypatches `run.run_deepear`/`run.run_deepfund`, confirmed
by grep -- see extract-run-mode-handlers-deepear-deepfund-pipeline's
proposal.md audit), so these tests stub the two phases directly on the
runner.modes.pipeline module rather than on `run`.
"""

import argparse

import runner.modes.pipeline as pipeline_module
from run import run_full_pipeline


def _make_args(**overrides):
    base = dict(
        skip_deepear=False,
        skip_deepfund=False,
        continue_on_error=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_skip_deepear_only_runs_deepfund(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 0)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args(skip_deepear=True))

    assert exit_code == 0
    assert calls == ["deepfund"]


def test_skip_deepfund_only_runs_deepear(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 0)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args(skip_deepfund=True))

    assert exit_code == 0
    assert calls == ["deepear"]


def test_skip_both_runs_neither_phase(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 0)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args(skip_deepear=True, skip_deepfund=True))

    assert exit_code == 0
    assert calls == []


def test_neither_skipped_runs_both_phases_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 0)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args())

    assert exit_code == 0
    assert calls == ["deepear", "deepfund"]


def test_deepear_failure_short_circuits_without_continue_on_error(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 1)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args(continue_on_error=False))

    assert exit_code == 1
    assert calls == ["deepear"]


def test_deepear_failure_continues_when_continue_on_error(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline_module, "run_deepear", lambda args: calls.append("deepear") or 1)
    monkeypatch.setattr(pipeline_module, "run_deepfund", lambda args: calls.append("deepfund") or 0)

    exit_code = run_full_pipeline(_make_args(continue_on_error=True))

    assert exit_code == 1
    assert calls == ["deepear", "deepfund"]
