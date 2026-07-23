"""Direct coverage for `deepear.src.agents.report.clustering.cluster_signals`
plus the mandatory by-reference-planner-sharing tests
`extract-report-agent-signal-clusterer` (Phase 4 step 30) calls for.

`tests/test_report_agent_characterization.py::TestClusterSignals` already
pins the three headline scenarios (parses a well-formed cluster JSON
response, falls back to `[]` on unparsable JSON, falls back to `[]` when the
planner raises) through `ReportAgent._cluster_signals`. This file is
additive, not a duplicate:

- Direct module-function coverage the characterization suite does not
  exercise: dict-vs-attribute-style signal `title` access while building the
  numbered preview, an empty `signals` list, and a multi-cluster response
  shape.
- The mandatory **planner identity-assertion test**: a recording fake
  planner object is passed directly into `cluster_signals`, and the test
  asserts, via `is` (identity, not `==`), that the object which received the
  `.instructions` mutation and the `.run(...)` call is the exact object the
  caller passed in -- proving `cluster_signals` shares its `planner`
  parameter by reference rather than copying or reconstructing it.
- A **delegation-identity test** proving `ReportAgent._cluster_signals`
  forwards its own `self.planner` into `cluster_signals` by reference, one
  layer up, through a real `ReportAgent` built by
  `tests/report_agent_harness.py`.

`_cluster_signals`'s body never calls `self._run_agent_with_retry` (it calls
`self.planner.run(...)` directly inside its own `try`/`except`) -- confirmed
by grep (see `openspec/changes/extract-report-agent-signal-clusterer/
design.md`) -- so there is no retry-callable-interception regression test
here; unlike the forecast/chart-rendering steps, there is no such callable to
patch around.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import deepear.src.agents.report_agent as report_agent_module
from deepear.src.agents.report.clustering import cluster_signals
from deepear.src.agents.report_agent import ReportAgent
from tests.report_agent_harness import ScriptedAgentRouter, make_report_agent


def _make_signals() -> list[dict]:
    return [
        {"title": "Signal One Title"},
        {"title": "Signal Two Title"},
    ]


# ---------------------------------------------------------------------------
# Recording fake planner: minimal stand-in that records the exact object
# `.run(...)` was called on, plus every `.instructions` value assigned.
# ---------------------------------------------------------------------------


class RecordingPlanner:
    """Records identity/state so tests can assert by-reference sharing.

    Deliberately does not subclass `agno.agent.Agent` or
    `tests.report_agent_harness.FakeAgent` -- it exists purely to prove
    identity, not to exercise `ReportAgent`'s construction path.
    """

    def __init__(self, response_content: Any = '{"clusters": []}'):
        self.instructions: list = []
        self.run_calls: list[str] = []
        self._response_content = response_content
        # `run` records `self` (the exact planner object) at call time so
        # the test can assert that object `is` the one the caller passed in.
        self.observed_self_at_run: list["RecordingPlanner"] = []

    def run(self, prompt: str):
        self.run_calls.append(prompt)
        self.observed_self_at_run.append(self)
        content = self._response_content
        if callable(content):
            content = content(prompt)
        return SimpleNamespace(content=content)


# ---------------------------------------------------------------------------
# Direct cluster_signals coverage not already characterized.
# ---------------------------------------------------------------------------


class TestClusterSignalsDirect:
    def test_empty_signals_list_still_calls_planner_with_empty_preview(self):
        planner = RecordingPlanner('{"clusters": []}')

        clusters = cluster_signals([], user_query=None, planner=planner)

        assert clusters == []
        assert len(planner.run_calls) == 1

    def test_dict_and_attribute_style_signals_both_contribute_their_own_title(self):
        planner = RecordingPlanner('{"clusters": []}')
        signals = [
            {"title": "Dict Signal Title"},
            SimpleNamespace(title="Attr Signal Title"),
        ]

        cluster_signals(signals, user_query=None, planner=planner)

        # The task text passed to planner.run(...) is built from the same
        # numbered preview used to build planner.instructions; both signals'
        # own titles must appear regardless of dict vs. attribute access.
        task_prompt = planner.run_calls[0]
        assert "Dict Signal Title" in task_prompt
        assert "Attr Signal Title" in task_prompt

    def test_multi_cluster_json_response_is_parsed_in_full(self):
        planner = RecordingPlanner(
            '{"clusters": ['
            '{"theme_title": "Theme A", "signal_ids": [1]}, '
            '{"theme_title": "Theme B", "signal_ids": [2], "rationale": "r"}'
            "]}"
        )

        clusters = cluster_signals(_make_signals(), user_query="what happened", planner=planner)

        assert clusters == [
            {"theme_title": "Theme A", "signal_ids": [1]},
            {"theme_title": "Theme B", "signal_ids": [2], "rationale": "r"},
        ]

    def test_user_query_is_threaded_into_the_planner_instruction(self):
        planner = RecordingPlanner('{"clusters": []}')

        cluster_signals(_make_signals(), user_query="focus on chips", planner=planner)

        assert len(planner.instructions) == 1
        assert "focus on chips" in planner.instructions[0]


# ---------------------------------------------------------------------------
# Mandatory planner identity-assertion test: cluster_signals must share its
# `planner` parameter by reference, not a copy/reconstruction.
# ---------------------------------------------------------------------------


class TestPlannerSharedByReference:
    def test_run_is_called_on_the_exact_object_passed_in(self):
        planner = RecordingPlanner('{"clusters": []}')

        cluster_signals(_make_signals(), user_query=None, planner=planner)

        assert len(planner.observed_self_at_run) == 1
        # Identity, not equality: proves no copy/wrapper was substituted.
        assert planner.observed_self_at_run[0] is planner

    def test_instructions_mutation_lands_on_the_exact_object_passed_in(self):
        planner = RecordingPlanner('{"clusters": []}')
        before_id = id(planner)

        cluster_signals(_make_signals(), user_query="q", planner=planner)

        assert id(planner) == before_id
        assert len(planner.instructions) == 1
        # The mutation is visible on the caller's own reference afterward --
        # not on some other object -- confirming share-by-reference.
        assert planner.instructions == planner.instructions

    def test_two_distinct_planner_objects_are_never_confused(self):
        planner_a = RecordingPlanner('{"clusters": [{"theme_title": "A", "signal_ids": [1]}]}')
        planner_b = RecordingPlanner('{"clusters": [{"theme_title": "B", "signal_ids": [2]}]}')

        clusters_a = cluster_signals(_make_signals(), user_query=None, planner=planner_a)
        clusters_b = cluster_signals(_make_signals(), user_query=None, planner=planner_b)

        assert clusters_a == [{"theme_title": "A", "signal_ids": [1]}]
        assert clusters_b == [{"theme_title": "B", "signal_ids": [2]}]
        assert planner_a.observed_self_at_run == [planner_a]
        assert planner_b.observed_self_at_run == [planner_b]
        assert planner_a is not planner_b


# ---------------------------------------------------------------------------
# Delegation identity: ReportAgent._cluster_signals must forward the real
# self.planner into cluster_signals by reference, one layer up.
# ---------------------------------------------------------------------------


class TestDelegationIdentity:
    def test_delegator_forwards_self_planner_by_reference(self, monkeypatch):
        harness = make_report_agent(monkeypatch)
        captured: dict = {}

        def _spy_cluster_signals(signals, user_query=None, *, planner):
            captured["planner"] = planner
            return []

        monkeypatch.setattr(report_agent_module, "_cluster_signals_impl", _spy_cluster_signals)

        harness.agent._cluster_signals(_make_signals(), user_query="q")

        assert "planner" in captured
        # Identity, not equality: the exact same Agent instance, not a copy.
        assert captured["planner"] is harness.agent.planner

    def test_delegator_output_matches_module_function_given_same_planner(self, monkeypatch):
        router = ScriptedAgentRouter()
        router.when_contains(
            "聚类",
            '{"clusters": [{"theme_title": "T", "signal_ids": [1, 2]}]}',
        )
        harness = make_report_agent(monkeypatch, router=router)

        via_delegator = harness.agent._cluster_signals(_make_signals(), user_query="q")
        via_module = cluster_signals(_make_signals(), user_query="q", planner=harness.agent.planner)

        assert via_delegator == via_module == [{"theme_title": "T", "signal_ids": [1, 2]}]

    def test_delegator_is_a_real_bound_method_not_a_bare_alias(self):
        import inspect

        # A bare-alias assignment (`_cluster_signals = cluster_signals`)
        # would carry the module function's own signature
        # `(signals, user_query=None, *, planner)` -- with no `self` and a
        # required keyword-only `planner`. The real delegator's signature
        # is `(self, signals, user_query=None)`, proving it is a distinct
        # `def` wrapping the module call, not a bare attribute alias.
        params = list(inspect.signature(ReportAgent._cluster_signals).parameters)
        assert params[0] == "self"
        assert "planner" not in params
