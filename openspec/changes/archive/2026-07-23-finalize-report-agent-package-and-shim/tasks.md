## 1. Audit

- [x] 1.1 Capture the pre-move name inventory: `python -c "import deepear.src.agents.report_agent as m; print(sorted(n for n in dir(m) if not n.startswith('__')))"` — 45 names (`ReportAgent` plus 44 incidental module globals: `Agent`, `Model`, `DatabaseManager`, `InMemoryRAG`, `StockTools`, `ForecastAgent`, `ClusterContext`, `ForecastResult`, typing aliases, `re`/`time`/`datetime`/`timedelta`/`SimpleNamespace`, `logger`, every `_*_impl` alias, every `deepear.src.prompts.report_agent` function).
- [x] 1.2 `git grep -n "report_agent" tests/ deepear/ backtest/ deepfund/ shared/ | grep -v "agents/report/"` — classify every hit: plain `ReportAgent` imports (satisfied by re-export), and exactly five patch sites that read/write a module-global name other than `ReportAgent` (`tests/report_agent_harness.py`'s two `monkeypatch.setattr(report_agent_module, "Agent"/"ForecastAgent", ...)`, `tests/test_report_agent_characterization.py`'s and `tests/test_report_agent_citations.py`'s string-path `Agent` patches, `tests/test_report_clustering.py`'s `_cluster_signals_impl` patch, and `tests/test_report_chart_renderer.py`'s two `report_agent_module.Agent` read/patch sites).
- [x] 1.3 Confirm no file does `from agents.report_agent import ...` (bare `agents`) — `tests/conftest.py`'s `_pin_ambiguous_package_resolution` pins bare `agents` to `deepfund/src/agents`, which has no `report_agent` module; this spelling was never valid and needs no shim support.
- [x] 1.4 Confirm no `deepear/src/agents/report/*.py` leaf module imports `deepear.src.agents.report_agent` or `deepear.src.agents.report.agent` (no circular-import risk from the new module) — verified via `grep -rn "^from deepear\|^import deepear" deepear/src/agents/report/*.py`.
- [x] 1.5 Confirm `deepear-internal` consumers (`deepear/src/agents/__init__.py`, `deepear/src/main_flow.py`) only ever reference `ReportAgent`, never any other `report_agent` module global.

## 2. Implementation

- [x] 2.1 Add `deepear/src/agents/report/agent.py`: move `ReportAgent` verbatim (class body character-for-character), with its own copy of every module-level import the class needs.
- [x] 2.2 Collapse `deepear/src/agents/report_agent.py` to a compatibility-shim docstring plus `from deepear.src.agents.report.agent import ReportAgent` and `__all__ = ["ReportAgent"]`.
- [x] 2.3 Build out `deepear/src/agents/report/__init__.py`: re-export `ReportAgent` and every leaf module's public function by explicit name (not `from .agent import *`); list every re-export in `__all__`.
- [x] 2.4 `tests/report_agent_harness.py`: `import deepear.src.agents.report_agent as report_agent_module` → `import deepear.src.agents.report.agent as report_agent_module`; update the module/function docstrings that described the old namespace as the patch seam.
- [x] 2.5 `tests/test_report_agent_characterization.py::test_tool_model_defaults_to_model_when_omitted`: rewrite the string-path patch `"deepear.src.agents.report_agent.Agent"` → `"deepear.src.agents.report.agent.Agent"`.
- [x] 2.6 `tests/test_report_agent_citations.py::test_non_incremental_report_generation_normalizes_citations`: same string-path rewrite.
- [x] 2.7 `tests/test_report_chart_renderer.py`: both local `import deepear.src.agents.report_agent as report_agent_module` sites (inside `TestChartRendererModuleFunctionDirectly`) → `import deepear.src.agents.report.agent as report_agent_module`; update the module docstring and the two affected test docstrings.
- [x] 2.8 `tests/test_report_clustering.py`: `import deepear.src.agents.report_agent as report_agent_module` → `import deepear.src.agents.report.agent as report_agent_module`.
- [x] 2.9 Experimentally verify the seam moved: temporarily patch `deepear.src.agents.report_agent.Agent` (assigned directly as an attribute, since the shim does not re-export it) and construct a `ReportAgent` — confirm the patch has no effect (real `agno.agent.Agent` construction is attempted); then confirm patching `deepear.src.agents.report.agent.Agent` does intercept.

## 3. Tests

- [x] 3.1 Add `tests/test_report_agent_shim.py`: old import spellings resolve to the same object (`from deepear.src.agents.report_agent import ReportAgent`, module-attribute access, `deepear/src/agents/__init__.py`'s own import); the shim class *is* the package class (`is` identity, `__module__` check); patching the new namespace intercepts real construction and a full `generate_report()` call end-to-end; patching the shim (which has no `Agent` attribute) does not; `deepear.src.agents.report`'s `__init__.py` re-exports resolve to the same objects as their fully-qualified imports; `__all__` lists only actually-present attributes.
- [x] 3.2 Confirm `tests/test_report_agent_characterization.py` (32 tests), `tests/test_report_agent_citations.py` (1 test), `tests/test_report_chart_renderer.py` (20 tests), `tests/test_report_clustering.py` (13 tests), `tests/test_report_citations_module.py`, `tests/test_report_forecast_ticker.py`, `tests/test_report_pure_functions.py`, `tests/test_report_retry_helper.py` all still pass unchanged in behavior (132 report-suite tests total, all green).

## 4. Gates

- [x] 4.1 `ruff check .` clean.
- [x] 4.2 `rtk proxy python -m pytest tests/test_report_agent_characterization.py tests/test_report_agent_citations.py tests/test_report_chart_renderer.py tests/test_report_clustering.py tests/test_report_citations_module.py tests/test_report_forecast_ticker.py tests/test_report_pure_functions.py tests/test_report_retry_helper.py tests/test_report_agent_shim.py -q` — 132 pre-existing + 12 new = 144 passed, 0 failed.
- [x] 4.3 `rtk proxy python -m pytest tests/ -q` run twice, back to back — both runs 1088 passed (1076 baseline + 12 new), 10 skipped, 0 failed.
- [x] 4.4 `openspec validate --changes` passes.
- [x] 4.5 `python -W error::SyntaxWarning -c "import deepear.src.agents.report_agent; import deepear.src.agents.report; import deepear.src.agents.report.agent; import deepear.src.agents"` — no warning raised.
- [x] 4.6 Record final `deepear/src/agents/report_agent.py` line count (34) in the commit message.
