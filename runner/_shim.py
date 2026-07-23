"""Module-resolution shim for internal caller->callee calls that cross the
run.py / runner/ package boundary.

When a function that used to live in run.py moves into runner/ alongside
a callee it invokes internally, a bare-name call inside the moved module
resolves against *that module's* globals, not run.py's. Tests that
monkeypatch the callee by string path (`monkeypatch.setattr('run.<callee>',
...)`) then silently stop taking effect, because the patch lands on the
`run` module's attribute while the real call is reading
`runner.<module>`'s own attribute instead.

`run_module()` returns whichever module currently plays the role of the
public entry point: the imported `run` module during normal test/import
usage, or `__main__` when `run.py` is executed directly as a script (in
which case Python never registers it under the name "run").
"""

import sys


def run_module():
    """The public `run` module (or __main__ when run.py is executed directly)."""
    mod = sys.modules.get("run")
    if mod is not None and hasattr(mod, "_validate_environment"):
        return mod
    return sys.modules.get("__main__")
