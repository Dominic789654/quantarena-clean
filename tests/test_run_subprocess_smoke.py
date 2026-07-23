"""Real subprocess smoke test for run.py's `__main__` execution path.

Every other run.py test imports its functions directly and calls them
with fake executors / monkeypatches -- none of them actually
`subprocess.run([sys.executable, "run.py", ...])`. That leaves the
`__main__`-registration fallback in `runner._shim.run_module()` (used
when `sys.modules.get("run")` is `None`, i.e. run.py was executed as a
script rather than imported as a module) completely uncovered.

Added by the add-run-module-shim-and-env-validation change
(docs/refactor_program_plan.md Phase 2, step 4 of 8).
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_check_env_exits_zero_via_real_subprocess():
    """`python run.py --check-env` must exit 0 when run as a real script.

    This exercises run.py's actual `if __name__ == "__main__":` entry
    point. Note: --check-env returns before any `_shim.run_module()`
    call site, so the shim's `__main__` fallback branch is exercised by
    test_full_pipeline_skip_flags_via_real_subprocess below, not here.
    """
    result = subprocess.run(
        [sys.executable, "run.py", "--check-env"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"run.py --check-env exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_full_pipeline_skip_flags_via_real_subprocess():
    """`python run.py --mode full --skip-deepear --skip-deepfund` exits 0
    as a real script.

    Unlike --check-env, this path reaches main()'s `print_banner` shim
    call site while the module is registered as `__main__` (run.py was
    exec'd, never imported), so it genuinely walks the
    `runner._shim.run_module()` fallback branch
    (`sys.modules.get("__main__")`).
    """
    result = subprocess.run(
        [sys.executable, "run.py", "--mode", "full", "--skip-deepear", "--skip-deepfund"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"run.py --mode full (both skips) exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
