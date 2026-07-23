"""Bootstrap helpers extracted from run.py: tushare token-file repair and
dotenv loading.

Moved verbatim (behavior-preserving) from run.py by the
extract-run-bootstrap-module change (docs/refactor_program_plan.md
Phase 2). run.py re-exports these names so every existing
`run.<name>` monkeypatch string path and `from run import <name>`
import keeps resolving.
"""

import os
import warnings


def _fix_tushare_token_file() -> None:
    """
    Fix the tushare token file issue before importing anything else.

    Checks file permissions before attempting to remove corrupted token file.
    Silently continues if file cannot be removed (non-critical error).
    """
    tk_csv_path = os.path.expanduser("~/tk.csv")

    # Check if file exists
    if not os.path.exists(tk_csv_path):
        return

    # Check if we have write permission before attempting removal
    if not os.access(tk_csv_path, os.W_OK):
        warnings.warn(
            f"Cannot fix Tushare token file (permission denied): {tk_csv_path}. "
            f"You may need to remove it manually if it's corrupted.",
            RuntimeWarning,
            stacklevel=2
        )
        return

    try:
        # Try to validate file content
        try:
            import pandas as pd
            df = pd.read_csv(tk_csv_path)
            if df.empty or 'token' not in df.columns:
                # File is corrupted, remove it
                os.remove(tk_csv_path)
        except Exception:
            # Cannot read file (corrupted or locked), try to remove anyway
            os.remove(tk_csv_path)

    except PermissionError:
        # Permission denied during removal (race condition or changed permissions)
        warnings.warn(
            f"Permission denied when removing Tushare token file: {tk_csv_path}",
            RuntimeWarning,
            stacklevel=2
        )
    except OSError as e:
        # Other OS-level errors (file locked, etc.)
        warnings.warn(
            f"Could not remove Tushare token file {tk_csv_path}: {e}",
            RuntimeWarning,
            stacklevel=2
        )


def load_dotenv_file(env_path) -> None:
    """Load environment variables from a .env file.

    Lifted out of run.py's run_deepfund (unchanged logic): loads the
    given path with python-dotenv.
    """
    from dotenv import load_dotenv
    load_dotenv(env_path)
