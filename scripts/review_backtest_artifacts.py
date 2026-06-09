#!/usr/bin/env python3
"""Review multi-personality backtest artifacts for execution consistency."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quantarena.backtest_artifact_review import review_multi_personality_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", help="Path to reports/multi_personality/<run_id>")
    parser.add_argument(
        "--backtest-root",
        help="Path to reports/backtest. Defaults to the sibling backtest directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args(argv)

    review = review_multi_personality_artifacts(
        args.report_dir,
        backtest_root=args.backtest_root,
    )
    payload = review.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        status = "ok" if review.ok else "failed"
        print(f"Backtest artifact review: {status}")
        for finding in review.findings:
            prefix = finding.severity.upper()
            label = finding.personality or "comparison"
            print(f"{prefix}: {label} {finding.run_id}: {finding.message}")
    return 0 if review.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
