"""DeepEar mode handler extracted from run.py.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-mode-handlers-deepear-deepfund-pipeline change
(docs/refactor_program_plan.md Phase 2). run.py re-exports `run_deepear`
so existing `from run import run_deepear` imports keep resolving (grep
found zero `monkeypatch.setattr("run.run_deepear", ...)` usages -- see
the change's proposal.md audit -- so no `_shim` indirection is needed
for its internal calls).

Resolves the project root via `get_project_root()` at the two call
sites that used run.py's former module-level `PROJECT_ROOT` global,
mirroring the substitution already used in `runner/config_discovery.py`
and `runner/env_validation.py`.
"""

import argparse

from shared.utils.path_manager import get_project_root

from runner import _shim
from runner.env_validation import _validate_environment


def run_deepear(args: argparse.Namespace) -> int:
    """Run DeepEar intelligence gathering."""
    # Route through the public `run` module so monkeypatch.setattr(
    # "run._validate_environment", ...) keeps working post-extraction.
    validate_environment = getattr(_shim.run_module(), "_validate_environment", None) or _validate_environment
    if not validate_environment(mode="deepear"):
        return 1

    print("\n" + "=" * 60)
    print("Mode: DeepEar Intelligence Gathering")
    print("=" * 60 + "\n")

    try:
        # Import DeepEar modules
        from main_flow import SignalFluxWorkflow
        from utils.logging_setup import setup_file_logging, make_run_id

        project_root = get_project_root()

        # Setup logging
        run_id = args.run_id or make_run_id()
        log_dir = args.log_dir or str(project_root / "logs")
        log_path = setup_file_logging(run_id=run_id, log_dir=log_dir, level=args.log_level)

        print(f"Log file: {log_path}")
        print(f"Run ID: {run_id}")

        # Parse sources
        if args.sources.lower() in ["all", "financial", "social", "tech"]:
            sources = [args.sources]
        else:
            sources = [s.strip() for s in args.sources.split(",")]

        # Parse depth
        depth = args.depth
        try:
            depth = int(depth)
        except ValueError:
            pass  # Keep as 'auto' or original string

        # Create workflow
        workflow = SignalFluxWorkflow(isq_template_id=args.template or "default_isq_v1")

        # Run workflow
        result = workflow.run(
            sources=sources,
            wide=args.wide or 10,
            depth=depth,
            query=args.query or "扫描A股市场热点",
            run_id=run_id,
            checkpoint_dir=args.checkpoint_dir or str(project_root / "reports" / "checkpoints"),
            resume=args.resume,
            resume_from=args.resume_from or "report",
            concurrency=args.concurrency or 1,
        )

        print(f"\n{'=' * 60}")
        print("DeepEar completed successfully!")
        print(f"Output: {result}")
        return 0

    except ImportError as e:
        print(f"ERROR: Failed to import DeepEar modules: {e}")
        print("Make sure DeepEar is properly installed.")
        return 1
    except Exception as e:
        print(f"ERROR: DeepEar execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
