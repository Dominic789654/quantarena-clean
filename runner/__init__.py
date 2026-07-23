"""runner: decomposed pieces of run.py (docs/refactor_program_plan.md Phase 2).

run.py stays as a thin entry point that re-exports every name here so
existing `run.<name>` monkeypatch string paths and `from run import
<name>` imports keep resolving while the implementation lives in this
package.
"""
