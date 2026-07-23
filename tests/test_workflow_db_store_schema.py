"""DDL schema-smoke test for backtest.workflow.db_store._setup_database.

No test previously asserted that _setup_database actually creates the
four tables and five indices BacktestWorkflowAdapter relies on (see
docs/refactor_program_plan.md Phase 3 step 4,
extract-workflow-db-store). This test exercises the extracted module
function directly against a tmp_path database file.
"""

import sqlite3

from backtest.workflow.db_store import _setup_database

EXPECTED_TABLES = {"config", "portfolio", "decision", "signal"}
EXPECTED_INDICES = {
    "idx_config_exp_name",
    "idx_portfolio_config",
    "idx_portfolio_trading_date",
    "idx_decision_portfolio",
    "idx_signal_portfolio",
}


def _sqlite_master_names(db_path: str, obj_type: str) -> set:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = ?", (obj_type,)
        ).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def test_setup_database_creates_expected_tables(tmp_path):
    db_path = tmp_path / "adapter_schema.db"

    _setup_database(str(db_path))

    tables = _sqlite_master_names(str(db_path), "table")
    assert EXPECTED_TABLES.issubset(tables)


def test_setup_database_creates_expected_indices(tmp_path):
    db_path = tmp_path / "adapter_schema.db"

    _setup_database(str(db_path))

    indices = _sqlite_master_names(str(db_path), "index")
    assert EXPECTED_INDICES.issubset(indices)


def test_setup_database_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "adapter_schema.db"
    assert not db_path.parent.exists()

    _setup_database(str(db_path))

    assert db_path.parent.exists()
    assert db_path.exists()


def test_setup_database_uses_wal_journal_mode(tmp_path):
    """The one behavior change in this batch: adopts shared.db's pragmas."""
    db_path = tmp_path / "adapter_schema.db"

    _setup_database(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert str(journal_mode).lower() == "wal"


def test_setup_database_is_idempotent(tmp_path):
    db_path = tmp_path / "adapter_schema.db"

    _setup_database(str(db_path))
    _setup_database(str(db_path))  # Should not raise

    tables = _sqlite_master_names(str(db_path), "table")
    assert EXPECTED_TABLES.issubset(tables)
