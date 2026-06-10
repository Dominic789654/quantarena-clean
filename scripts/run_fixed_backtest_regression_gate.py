#!/usr/bin/env python3
"""Run QuantArena's fixed backtest regression gate."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_ensure_project_root_on_path()

from quantarena.fixed_backtest_regression_gate import main


if __name__ == "__main__":
    raise SystemExit(main())
