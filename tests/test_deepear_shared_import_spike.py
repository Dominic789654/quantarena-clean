"""Spike: prove `deepear/src/utils/database_manager.py` can `from shared.db
import ...` under all three of its real load mechanisms, in a fresh
subprocess that never calls `shared.utils.path_manager.setup_paths()`.

This intentionally does NOT rely on pytest's own sys.path wiring (see
tests/conftest.py's `setup_paths()` call) — each test below spawns a
completely fresh `sys.executable` subprocess with a hand-picked, minimal
environment that mirrors how each mechanism is actually reached in
production, and asserts the import succeeds there.

See openspec/changes/spike-deepear-importlib-shared-import/design.md for
the narrative writeup of what these subprocess runs found.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEEPEAR_DIR = PROJECT_ROOT / "deepear"
DEEPFUND_SRC = PROJECT_ROOT / "deepfund" / "src"

# A neutral cwd that is NOT the project root and has no relationship to it,
# so that `-c`'s automatic `sys.path[0] = cwd` can never accidentally hand
# the child process a free pass to the project's packages.
_NEUTRAL_CWD = tempfile.gettempdir()


def _run(code: str, env_overrides: dict) -> subprocess.CompletedProcess:
    """Run `code` in a brand-new subprocess with a minimal, explicit env.

    `env_overrides` completely determines the environment beyond PATH (and
    a couple of interpreter housekeeping vars) — no ambient PYTHONPATH,
    VIRTUAL_ENV, etc. leaks in, and `setup_paths()` is never called.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        # Keep the interpreter itself sane (locale/encoding) without
        # granting any extra import surface.
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=_NEUTRAL_CWD,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestMechanism1NormalImport:
    """`from deepear.src.utils.database_manager import DatabaseManager`
    used directly (deepear/src/main_flow.py, news_tools.py, stock_tools.py,
    trend_agent.py, ... and backtest/data_loader.py) — a plain dotted
    import of the fully-qualified module path.
    """

    def test_resolves_with_zero_path_configuration(self):
        """No PYTHONPATH, no setup_paths(), neutral cwd: still resolves.

        `quantarena` is installed editable (`pip install -e .`) in the venv
        that runs these tests, and `[tool.setuptools.packages.find]`
        registers `deepear`, `deepfund`, and `shared` as top-level
        importable packages. That editable-install finder — not any
        sys.path hack — is what makes the fully-qualified dotted import
        (and the `from shared.db import ...` inside it) resolve
        unconditionally.
        """
        result = _run(
            """
            from deepear.src.utils.database_manager import DatabaseManager
            import shared.db
            assert DatabaseManager.__module__ == "deepear.src.utils.database_manager"
            print("MECH1_OK")
            """,
            env_overrides={},
        )
        assert result.returncode == 0, result.stderr
        assert "MECH1_OK" in result.stdout


class TestMechanism2DeepearClientImportlibHack:
    """deepfund/src/integrations/deepear_client.py's
    `importlib.util.spec_from_file_location` loader (around lines 304-350,
    439), reached in production via the bare `from integrations.deepear_client
    import DeepEarClient` in deepfund/src/agents/analysts/deepear_intelligence.py.
    """

    def test_resolves_with_only_deepfund_src_on_pythonpath(self):
        """Bare `integrations` needs deepfund/src on sys.path (that's how
        production reaches this mechanism: setup_paths() puts it there).
        Deliberately do NOT add the project root to PYTHONPATH — prove
        `shared.db` still resolves inside the importlib-loaded
        database_manager module purely via the editable-install finder.
        """
        result = _run(
            """
            import sys, importlib.util

            import integrations.deepear_client as dc
            deepear_src = str(dc.DEEPEAR_SRC_PATH)

            def load_module_from_path(module_name, file_path):
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module

            db_module = load_module_from_path(
                "utils.database_manager", f"{deepear_src}/utils/database_manager.py"
            )
            assert db_module.DatabaseManager is not None
            assert db_module.configure_sqlite_connection is not None
            print("MECH2_OK")
            """,
            env_overrides={
                "DEEPEAR_PATH": str(DEEPEAR_DIR),
                "PYTHONPATH": str(DEEPFUND_SRC),
            },
        )
        assert result.returncode == 0, result.stderr
        assert "MECH2_OK" in result.stdout

    def test_bare_integrations_import_fails_without_deepfund_src_on_path(self):
        """Sanity check for the above: `integrations` is NOT one of the
        editable install's registered top-level packages (only
        deepear*/deepfund*/quantarena*/shared*/trading*), so the bare
        import genuinely depends on deepfund/src being on sys.path —
        confirming the PYTHONPATH in the test above is load-bearing, not
        incidental.
        """
        result = _run(
            "import integrations.deepear_client\n",
            env_overrides={"DEEPEAR_PATH": str(DEEPEAR_DIR)},
        )
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr
        assert "integrations" in result.stderr


class TestMechanism3WorkerProcessImport:
    """deepfund/src/agents/analysts/technical.py:81-91 style import,
    executed inside a worker process spawned by `ProcessPoolExecutor`
    (backtest/multi_personality_engine.py uses the default Linux `fork`
    start method, so workers inherit the parent's already-configured
    sys.path/sys.modules rather than re-running any path setup).
    """

    def test_resolves_inside_a_forked_worker_with_zero_path_configuration(self):
        """No PYTHONPATH, no setup_paths() anywhere — parent or child."""
        result = _run(
            """
            import multiprocessing as mp

            def worker(q):
                try:
                    from deepear.src.utils.database_manager import DatabaseManager
                    q.put(("OK", DatabaseManager.__module__))
                except Exception as e:
                    q.put(("ERR", repr(e)))

            if __name__ == "__main__":
                ctx = mp.get_context("fork")
                q = ctx.Queue()
                p = ctx.Process(target=worker, args=(q,))
                p.start()
                status, detail = q.get(timeout=10)
                p.join(timeout=10)
                assert status == "OK", detail
                print("MECH3_OK", detail)
            """,
            env_overrides={},
        )
        assert result.returncode == 0, result.stderr
        assert "MECH3_OK" in result.stdout

    def test_resolves_inside_a_forked_worker_inheriting_pythonpath(self):
        """Same as above, but the parent (and thus the forked child) only
        has the project root on PYTHONPATH — the exact shape production
        gets from `setup_paths()` having run once before
        ProcessPoolExecutor spawns workers.
        """
        result = _run(
            """
            import multiprocessing as mp

            def worker(q):
                try:
                    from deepear.src.utils.database_manager import DatabaseManager
                    import shared.db
                    q.put(("OK", DatabaseManager.__module__))
                except Exception as e:
                    q.put(("ERR", repr(e)))

            if __name__ == "__main__":
                ctx = mp.get_context("fork")
                q = ctx.Queue()
                p = ctx.Process(target=worker, args=(q,))
                p.start()
                status, detail = q.get(timeout=10)
                p.join(timeout=10)
                assert status == "OK", detail
                print("MECH3_PYTHONPATH_OK", detail)
            """,
            env_overrides={"PYTHONPATH": str(PROJECT_ROOT)},
        )
        assert result.returncode == 0, result.stderr
        assert "MECH3_PYTHONPATH_OK" in result.stdout
