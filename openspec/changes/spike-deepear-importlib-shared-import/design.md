## Context

`add-wal-busytimeout-to-deepear-db` wants to add
`from shared.db import configure_sqlite_connection, ensure_parent_dir` to
the top of `deepear/src/utils/database_manager.py`. That module is loaded
three different ways in production, none of which are pytest:

1. **Normal dotted import** — `from deepear.src.utils.database_manager
   import DatabaseManager`, used directly by `deepear/src/main_flow.py`,
   `news_tools.py`, `stock_tools.py`, `search_tools.py`,
   `sentiment_tools.py`, `predictor/training.py`, `tools/toolkits.py`,
   `agents/{report_agent,trend_agent,fin_agent,forecast_agent}.py`, and
   `backtest/data_loader.py`.
2. **deepfund's importlib hack** —
   `deepfund/src/integrations/deepear_client.py`'s `_analyze_ticker_impl`
   (around lines 304-350) uses `importlib.util.spec_from_file_location` to
   load `database_manager.py` under the synthetic module name
   `"utils.database_manager"` and injects it into `sys.modules` directly,
   bypassing normal package resolution for the loaded module itself. It's
   reached via a bare `from integrations.deepear_client import
   DeepEarClient` in `deepfund/src/agents/analysts/deepear_intelligence.py`.
3. **Worker-process import** —
   `deepfund/src/agents/analysts/technical.py:81` does
   `from deepear.src.utils.database_manager import DatabaseManager` inside
   `_load_backtest_prices`, which runs inside `ProcessPoolExecutor` workers
   spawned by `backtest/multi_personality_engine.py`. No `set_start_method`
   or `get_context("spawn")` call exists anywhere in the repo, so
   `ProcessPoolExecutor` uses the Linux default `fork` start method: workers
   inherit the parent's already-initialized `sys.path`/`sys.modules` rather
   than re-running any path setup.

None of these three call sites are reached through pytest, and none of them
call `shared.utils.path_manager.setup_paths()` on their own — mechanism 2's
own module-level code only does `sys.path.insert(0, DEEPEAR_SRC_PATH)`
(deepear/src, not the project root, not `shared`). The open question this
spike answers: does `from shared.db import ...` inside
`database_manager.py` actually resolve under all three, in a fresh process
that never calls `setup_paths()`?

## Goals / Non-Goals

**Goals:** empirically prove (or disprove) that all three load mechanisms
resolve `shared.db`, using subprocesses that replicate production's actual
environment shape rather than pytest's `conftest.py`-driven `setup_paths()`.
Decide, from evidence, whether `database_manager.py` needs defensive
fallback import code before `add-wal-busytimeout-to-deepear-db` lands.

**Non-Goals:** changing any production behavior; changing
`shared.utils.path_manager`; making the spike test itself part of the
"three mechanisms" contract (it just documents/regression-tests the
resolution, it doesn't formalize the load paths as a public API).

## Method

`tests/test_deepear_shared_import_spike.py` spawns a fresh
`subprocess.run([sys.executable, "-c", <code>], cwd=<neutral tmp dir>,
env=<explicit minimal dict>)` per mechanism. The env dict is built from
scratch (only `PATH`/`LANG` plus whatever each mechanism needs) — no
inherited `PYTHONPATH`, no inherited `VIRTUAL_ENV`, and the cwd is
deliberately *not* the project root, so `-c`'s automatic
`sys.path[0] = cwd` can never accidentally hand a test a free pass to the
project's packages. `setup_paths()` is never called in any child process.

## Findings

**All three mechanisms resolve `shared.db` — no fallback code needed.**

The decisive, initially-surprising finding: `quantarena` is installed
**editable** (`pip install -e .`) in `.venv_unified`
(`pip show quantarena` → `Editable project location:
/home/liuxiang/quantarena-clean`), and `pyproject.toml`'s
`[tool.setuptools.packages.find]` (`include = ["deepear*", "deepfund*",
"quantarena*", "shared*", "trading*"]`) registers `deepear`, `deepfund`,
and `shared` as top-level importable packages via the editable-install
meta path finder (`__editable__.quantarena-0.1.0.finder.__path_hook__`,
visible in `sys.path`). That finder makes fully-qualified dotted imports
like `deepear.src.utils.database_manager` and `shared.db` resolve
**unconditionally** — independent of `sys.path` content, cwd, `PYTHONPATH`,
or whether `setup_paths()` ever ran. `shared.utils.path_manager.setup_paths()`
exists to disambiguate *bare* (non-dotted) imports like `utils.*`,
`agents.*`, `config.*` — a separate, narrower concern from `shared.db`
resolution.

Per mechanism:

1. **Normal dotted import**: resolves with **zero** path configuration —
   confirmed with a fully stripped env (no `PYTHONPATH`, neutral cwd,
   `env -i`-style). Purely the editable-install finder at work; the
   `from shared.db import ...` inside `database_manager.py` never needed
   anything else.

2. **deepfund's importlib hack**: the `spec_from_file_location`/
   `exec_module` loading of `database_manager.py` under the synthetic name
   `"utils.database_manager"` does **not** interfere with normal import
   resolution for statements *inside* the loaded file — Python's import
   machinery for `from shared.db import ...` runs exactly as it would for
   any other module, regardless of how the enclosing module itself was
   injected into `sys.modules`. Confirmed resolving with only
   `deepfund/src` on `PYTHONPATH` (no project root added explicitly) — the
   bare `import integrations.deepear_client` needs `deepfund/src` on
   `sys.path` (that bare top-level name is *not* one of the editable
   install's registered packages — verified by a negative-control test
   that the bare import fails with `ModuleNotFoundError` when
   `deepfund/src` isn't on `PYTHONPATH`), but the `shared.db` resolution
   *inside* the hack-loaded module is unaffected by that and resolves via
   the editable-install finder regardless.

3. **Worker-process import (fork)**: confirmed resolving inside an actual
   `multiprocessing.get_context("fork")` child process, both with zero path
   configuration and with only the project root on `PYTHONPATH` (mirroring
   what `setup_paths()` would have given the parent before
   `ProcessPoolExecutor` forks workers). Fork semantics (copy-on-write
   address space, inherited `sys.modules`/`sys.path`) mean whatever the
   parent resolved, the child resolves too — no separate proof needed
   there, but the test exercises the actual fork boundary rather than
   asserting the inheritance argument by inspection.

## Decisions

1. **No fallback/defensive import code added.** The originally-anticipated
   fallback (`try/except ImportError` around `from shared.db import ...`
   with inline sqlite3-based pragma functions) is unnecessary — every real
   load mechanism resolves `shared.db` today, and the resolution is backed
   by packaging configuration (`pyproject.toml`), not a fragile runtime
   convention. `add-wal-busytimeout-to-deepear-db` adds the import
   unconditionally.
2. **The spike test is a permanent regression test, not a throwaway
   script.** It stays in `tests/` after this change archives, guarding
   against future changes to `pyproject.toml`'s package discovery or to
   the three load sites silently breaking this invariant.
3. Kept the mechanism-2 negative control (bare `integrations` import
   failing without `deepfund/src` on `PYTHONPATH`) in the spike to make the
   positive result's causality legible — it proves the `PYTHONPATH` in
   that test is load-bearing for reaching the mechanism at all, not just
   incidental noise around a resolution that would have happened anyway.

## Risks / Trade-offs

- This finding is contingent on the editable install remaining in place in
  whatever venv runs deepear/deepfund code. A non-editable
  (`pip install .` / wheel) deployment would *not* get the same
  unconditional resolution for the normal/worker-process mechanisms and
  would fall back to depending on `setup_paths()` (or equivalent
  `PYTHONPATH`) having run — which is already true today for every other
  `shared.*`/`deepfund.*`/`deepear.*` consumer in this codebase, so this
  isn't a new risk introduced by adopting `shared.db` here.
