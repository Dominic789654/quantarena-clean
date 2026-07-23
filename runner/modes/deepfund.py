"""DeepFund mode handler extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-mode-handlers-deepear-deepfund-pipeline change
(docs/refactor_program_plan.md Phase 2). run.py re-exports `run_deepfund`
so existing `from run import run_deepfund` imports keep resolving (grep
found zero `monkeypatch.setattr("run.run_deepfund", ...)` usages -- see
the change's proposal.md audit -- so no `_shim` indirection is needed
for its internal calls).

Resolves the project root and deepfund src dir via `get_project_root()`
/ `get_deepfund_src()` at the call sites that used run.py's former
module-level `PROJECT_ROOT`/`DEEPFUND_SRC` globals, mirroring the
substitution already used in `runner/config_discovery.py` and
`runner/env_validation.py`.
"""

import argparse
import sys
from datetime import datetime

from shared.utils.path_manager import get_deepfund_src, get_project_root
from shared.utils.time_utils import now_utc

from runner.bootstrap import load_dotenv_file
from runner.config_discovery import _get_deepfund_config_candidates
from runner.env_validation import _validate_environment


def run_deepfund(args: argparse.Namespace) -> int:
    """Run DeepFund trading analysis."""
    # Validate environment for deepfund mode
    if not _validate_environment(mode="deepfund"):
        return 1

    print("\n" + "=" * 60)
    print("Mode: DeepFund Trading Analysis")
    print("=" * 60 + "\n")

    try:
        # Import DeepFund modules
        # main.py is directly in deepfund/src/
        import importlib.util
        deepfund_src = get_deepfund_src()
        main_path = deepfund_src / "main.py"
        spec = importlib.util.spec_from_file_location("deepfund_main", main_path)
        deepfund_main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deepfund_main_module)
        deepfund_main = deepfund_main_module.main

        # Load environment
        project_root = get_project_root()
        load_dotenv_file(project_root / ".env")

        # Determine config file
        config_file = args.config
        if not config_file:
            config_candidates = _get_deepfund_config_candidates(args.market)

            # Find first existing config
            for cfg in config_candidates:
                if cfg.exists():
                    config_file = str(cfg)
                    break
            else:
                config_file = str(config_candidates[0])

        print(f"Using config: {config_file}")

        # Parse trading date
        trading_date = args.date
        if not trading_date:
            # Default to today or last trading day
            trading_date = now_utc().strftime("%Y-%m-%d")

        try:
            datetime.strptime(trading_date, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR: Invalid date format: {trading_date}. Use YYYY-MM-DD.")
            return 1

        # Build sys.argv for deepfund_main
        sys.argv = [
            "deepfund",
            "--config", config_file,
            "--trading-date", trading_date,
        ]
        if args.local_db:
            sys.argv.append("--local-db")

        # Run DeepFund
        deepfund_main()

        print(f"\n{'=' * 60}")
        print("DeepFund completed successfully!")
        return 0

    except ImportError as e:
        print(f"ERROR: Failed to import DeepFund modules: {e}")
        print("Make sure DeepFund is properly installed.")
        return 1
    except Exception as e:
        print(f"ERROR: DeepFund execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
