"""runner.modes: run.py mode handlers (docs/refactor_program_plan.md Phase 2).

Each submodule holds one (or a closely related group of) mode handler
moved verbatim out of run.py. run.py re-exports every handler here so
existing `run.<name>` monkeypatch string paths and `from run import
<name>` imports keep resolving.
"""
