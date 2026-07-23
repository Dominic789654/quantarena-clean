"""Full pipeline (DeepEar + DeepFund) mode handler extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-mode-handlers-deepear-deepfund-pipeline change
(docs/refactor_program_plan.md Phase 2). run.py re-exports
`run_full_pipeline` so existing `from run import run_full_pipeline`
imports keep resolving.

`run_full_pipeline` calls `run_deepear` and `run_deepfund` internally.
Grep found zero `monkeypatch.setattr("run.run_deepear"|"run.run_deepfund"|
"run.run_full_pipeline", ...)` usages anywhere in tests/ (see the
change's proposal.md audit), so these are plain intra-package imports
from the sibling `runner.modes.deepear`/`runner.modes.deepfund` modules
-- no `_shim` indirection is needed.
"""

import argparse

from deepear.src.utils.stats import get_stats

from runner.modes.deepear import run_deepear
from runner.modes.deepfund import run_deepfund


def run_full_pipeline(args: argparse.Namespace) -> int:
    """Run complete pipeline: DeepEar + DeepFund."""
    print("\n" + "=" * 60)
    print("Mode: Full Pipeline (DeepEar + DeepFund)")
    print("=" * 60 + "\n")

    exit_code = 0

    # Phase 1: DeepEar Intelligence
    if not args.skip_deepear:
        deepear_exit = run_deepear(args)
        if deepear_exit != 0 and not args.continue_on_error:
            return deepear_exit
        exit_code = max(exit_code, deepear_exit)
    else:
        print("Skipping DeepEar phase...")

    # Phase 2: DeepFund Trading
    if not args.skip_deepfund:
        deepfund_exit = run_deepfund(args)
        if deepfund_exit != 0 and not args.continue_on_error:
            return deepfund_exit
        exit_code = max(exit_code, deepfund_exit)
    else:
        print("Skipping DeepFund phase...")

    print("\n" + "=" * 60)
    print("Full Pipeline completed!")
    print(f"{'=' * 60}")

    # 打印使用统计报告
    get_stats().print_report()

    return exit_code
