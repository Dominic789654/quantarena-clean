"""SQLite DDL and CRUD glue for BacktestWorkflowAdapter's isolated
per-run database (config/portfolio/decision/signal tables).

Ported from `BacktestWorkflowAdapter` instance methods by the
extract-workflow-db-store change (docs/refactor_program_plan.md Phase
3). Each function takes the `self.*` attributes its original method
body read as explicit parameters instead. Every raw `sqlite3.connect`
call site adopts `shared.db.configure_sqlite_connection` /
`ensure_parent_dir` (WAL + busy_timeout + synchronous=NORMAL) — see the
extract-workflow-db-store change's design.md for why this is safe for
this specific db file. `backtest/workflow_adapter.py` keeps same-named
delegator instance methods for all five functions so every existing
`self.<name>(...)` / `adapter.<name>(...)` call keeps working.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from shared.db import configure_sqlite_connection, ensure_parent_dir


def _create_temp_db() -> str:
    """Create a temporary SQLite database path for a backtest run."""
    from shared.utils.path_manager import get_project_root

    temp_dir = get_project_root() / "data" / "backtest"
    temp_dir.mkdir(parents=True, exist_ok=True)

    db_file = temp_dir / (
        f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}.db"
    )
    return str(db_file)


def _setup_database(db_path: str) -> None:
    """Initialize SQLite database with required tables."""
    # Ensure directory exists
    ensure_parent_dir(db_path)

    conn = configure_sqlite_connection(sqlite3.connect(db_path))
    cursor = conn.cursor()

    # Create config table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            id VARCHAR(36) PRIMARY KEY,
            exp_name VARCHAR(100) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tickers JSON NOT NULL,
            has_planner BOOLEAN NOT NULL DEFAULT FALSE,
            llm_model VARCHAR(50) NOT NULL,
            llm_provider VARCHAR(50) NOT NULL
        )
    ''')

    # Create portfolio table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio (
            id VARCHAR(36) PRIMARY KEY,
            config_id VARCHAR(36) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trading_date TIMESTAMP NOT NULL,
            cashflow DECIMAL(15,2) NOT NULL,
            total_assets DECIMAL(15,2) NOT NULL,
            positions JSON NOT NULL,
            FOREIGN KEY (config_id) REFERENCES config(id)
        )
    ''')

    # Create decision table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decision (
            id VARCHAR(36) PRIMARY KEY,
            portfolio_id VARCHAR(36) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trading_date TIMESTAMP NOT NULL,
            ticker VARCHAR(10) NOT NULL,
            llm_prompt TEXT NOT NULL,
            action VARCHAR(10) NOT NULL,
            shares INTEGER NOT NULL,
            price DECIMAL(15,2) NOT NULL,
            justification TEXT NOT NULL,
            FOREIGN KEY (portfolio_id) REFERENCES portfolio(id)
        )
    ''')

    # Create signal table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal (
            id VARCHAR(36) PRIMARY KEY,
            portfolio_id VARCHAR(36) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticker VARCHAR(10) NOT NULL,
            llm_prompt TEXT NOT NULL,
            analyst VARCHAR(50) NOT NULL,
            signal VARCHAR(10) NOT NULL,
            justification TEXT NOT NULL,
            FOREIGN KEY (portfolio_id) REFERENCES portfolio(id)
        )
    ''')

    # Create indices
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_exp_name ON config(exp_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_config ON portfolio(config_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_trading_date ON portfolio(trading_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision_portfolio ON decision(portfolio_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_portfolio ON signal(portfolio_id)')

    conn.commit()
    conn.close()

    logger.debug(f"Database initialized at {db_path}")


def _ensure_config(
    db_path: str,
    exp_name: str,
    tickers: List[str],
    llm_model: str,
    llm_provider: str,
) -> str:
    """Create or get config entry for this backtest."""
    conn = configure_sqlite_connection(sqlite3.connect(db_path))
    cursor = conn.cursor()

    # Check if config exists
    cursor.execute('SELECT id FROM config WHERE exp_name = ?', (exp_name,))
    row = cursor.fetchone()

    if row:
        conn.close()
        logger.debug(f"Found existing config: {row[0]}")
        return row[0]

    # Create new config
    config_id = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO config (id, exp_name, updated_at, tickers, has_planner, llm_model, llm_provider)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        config_id,
        exp_name,
        datetime.now().isoformat(),
        json.dumps(tickers),
        False,  # no planner for backtest
        llm_model,
        llm_provider
    ))

    conn.commit()
    conn.close()

    logger.info(f"Created backtest config: {config_id}, exp_name: {exp_name}")
    return config_id


def _get_or_create_portfolio(
    db_path: str,
    config_id: str,
    trading_date: str,
    current_portfolio: Dict[str, Any],
) -> Dict[str, Any]:
    """Get or create portfolio for the trading date."""
    conn = configure_sqlite_connection(sqlite3.connect(db_path))
    cursor = conn.cursor()

    # Create new portfolio entry for this day
    portfolio_id = str(uuid.uuid4())
    total_assets = current_portfolio["cashflow"] + sum(
        pos["value"] for pos in current_portfolio["positions"].values()
    )

    cursor.execute('''
        INSERT INTO portfolio (id, config_id, updated_at, trading_date, cashflow, total_assets, positions)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        portfolio_id,
        config_id,
        datetime.now().isoformat(),
        trading_date,  # Keep as string for our local DB
        current_portfolio["cashflow"],
        total_assets,
        json.dumps(current_portfolio["positions"])
    ))

    conn.commit()
    conn.close()

    current_portfolio["id"] = portfolio_id
    return current_portfolio.copy()


def _update_portfolio(
    db_path: str,
    current_portfolio: Dict[str, Any],
    trading_date: str,
) -> None:
    """Update portfolio in database after decisions."""
    conn = configure_sqlite_connection(sqlite3.connect(db_path))
    cursor = conn.cursor()

    total_assets = current_portfolio["cashflow"] + sum(
        pos["value"] for pos in current_portfolio["positions"].values()
    )

    cursor.execute('''
        UPDATE portfolio
        SET cashflow = ?, total_assets = ?, positions = ?, updated_at = ?
        WHERE id = ?
    ''', (
        current_portfolio["cashflow"],
        total_assets,
        json.dumps(current_portfolio["positions"]),
        datetime.now().isoformat(),
        current_portfolio["id"]
    ))

    conn.commit()
    conn.close()
