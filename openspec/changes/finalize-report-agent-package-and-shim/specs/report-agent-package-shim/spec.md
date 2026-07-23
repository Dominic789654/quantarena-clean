## ADDED Requirements

### Requirement: ReportAgent is defined in deepear/src/agents/report/agent.py
`deepear/src/agents/report/agent.py` SHALL define the `ReportAgent` class (with its `__init__`, `_get_forecast_agent`, `generate_report`, `_incremental_edit`, and every same-named delegator method to `deepear.src.agents.report.{retry,chart_sanitizer,structured_report,citations,ticker_utils,forecast_requests,chart_renderer,clustering}`), importable independently of `deepear.src.agents.report_agent`, with a class body byte-for-byte identical to the one `deepear/src/agents/report_agent.py` defined before this change.

#### Scenario: The class is importable directly from its new home
- **WHEN** `from deepear.src.agents.report.agent import ReportAgent` is executed without first importing `deepear.src.agents.report_agent`
- **THEN** the import succeeds and `ReportAgent` can be constructed and used exactly as before this change

### Requirement: deepear/src/agents/report_agent.py re-exports ReportAgent as a compatibility shim
`deepear/src/agents/report_agent.py` SHALL be a compatibility shim whose only re-export is `ReportAgent`, such that `from deepear.src.agents.report_agent import ReportAgent` keeps resolving to the exact same class object (`is` identity) as `from deepear.src.agents.report.agent import ReportAgent`, and SHALL NOT re-export `Agent`, `ForecastAgent`, `_cluster_signals_impl`, or any other name that was previously an incidental module global of `report_agent.py` but was never referenced by any consumer or test through that module path.

#### Scenario: Existing import statements keep working unchanged
- **WHEN** `from deepear.src.agents.report_agent import ReportAgent` is executed
- **THEN** the imported class is identical (`is`) to `deepear.src.agents.report.agent.ReportAgent`

#### Scenario: The shim carries no re-export of the old patch-target names
- **WHEN** `deepear.src.agents.report_agent` is imported and inspected
- **THEN** it has no `Agent` attribute (nor `ForecastAgent`, nor `_cluster_signals_impl`)

### Requirement: deepear/src/agents/report/__init__.py re-exports ReportAgent and every leaf module's public function
`deepear/src/agents/report/__init__.py` SHALL re-export `ReportAgent` and each leaf module's public function (`run_agent_with_retry`, `sanitize_json_chart_blocks`, `build_structured_report`, `make_cite_key`, `build_bibliography`, `render_references_section`, `inject_references`, `normalize_citations`, `clean_markdown`, `clean_ticker`, `signal_mentions_ticker`, `extract_forecast_requests`, `build_forecast_map`, `process_charts`, `cluster_signals`), each identical (`is`) to the object importable via its fully-qualified per-module path, and SHALL list every one of those names in `__all__`.

#### Scenario: Package-level import resolves to the same object as the fully-qualified import
- **WHEN** `from deepear.src.agents.report import ReportAgent` (or `cluster_signals`, or any other re-exported name) is executed
- **THEN** the imported object is identical (`is`) to the one obtained via its fully-qualified per-module import (e.g. `from deepear.src.agents.report.agent import ReportAgent`, `from deepear.src.agents.report.clustering import cluster_signals`)

### Requirement: ReportAgent's Agent/ForecastAgent/_cluster_signals_impl monkeypatch seam is deepear.src.agents.report.agent, not the shim
Monkeypatching `Agent`, `ForecastAgent`, or `_cluster_signals_impl` on the `deepear.src.agents.report.agent` module SHALL intercept every internal `ReportAgent` method call that reads those names (construction of the four internal agents, `_get_forecast_agent`'s lazy cache, and `_cluster_signals`'s delegation), while the equivalent patch applied to `deepear.src.agents.report_agent` (the shim) SHALL have no effect on `ReportAgent`'s behavior.

#### Scenario: Patching Agent on the new namespace intercepts construction and generate_report
- **WHEN** `monkeypatch.setattr("deepear.src.agents.report.agent.Agent", FakeAgentClass)` is applied before constructing a `ReportAgent` and calling `generate_report(...)`
- **THEN** every internal agent (planner, writer, editor, section_editor) is an instance of `FakeAgentClass`, and `generate_report`'s output reflects `FakeAgentClass`'s scripted responses

#### Scenario: Patching Agent on the shim module does not intercept construction
- **WHEN** `deepear.src.agents.report_agent.Agent` is set to a decoy class (via direct attribute assignment, since the shim does not re-export `Agent` at all) and a `ReportAgent` is constructed
- **THEN** construction proceeds using the real `agno.agent.Agent` class, unaffected by the decoy assignment

### Requirement: deepear/src/agents/__init__.py's import of ReportAgent keeps resolving
`deepear/src/agents/__init__.py`'s `from deepear.src.agents.report_agent import ReportAgent` statement SHALL continue to resolve to the same class as `deepear.src.agents.report.agent.ReportAgent`, unchanged by this move.

#### Scenario: The package-level agents import still works
- **WHEN** `import deepear.src.agents as agents_pkg; agents_pkg.ReportAgent` is accessed
- **THEN** it resolves without error to the same class as `deepear.src.agents.report.agent.ReportAgent`
