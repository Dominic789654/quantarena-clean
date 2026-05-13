import threading

from database.sqlite_helper import SQLiteDB
from database.supabase_helper import SupabaseDB
from util.logger import logger


_db_local = threading.local()
_fallback_db = None


def db_initialize(use_local_db: bool = False, db_path: str | None = None):
    """Initialize the database connection for the current thread."""
    global _fallback_db
    if use_local_db:
        _db = SQLiteDB()
        if db_path:
            _db.set_db_path(db_path)
        logger.info("SQLite database initialized")
    else:
        _db = SupabaseDB()
        logger.info("Supabase database initialized")
    _db_local.db = _db
    _fallback_db = _db


def get_db():
    """Get the database instance for the current thread."""
    return getattr(_db_local, "db", _fallback_db)

# Wrapper functions for backward compatibility
def save_decision(portfolio_id: str, ticker: str, prompt: str, decision, trading_date):
    """Save a trading decision to the database."""
    db = get_db()
    if db is None:
        logger.warning("Database not initialized, skipping save_decision")
        return None
    return db.save_decision(portfolio_id, ticker, prompt, decision, trading_date)

def save_signal(portfolio_id: str, analyst: str, ticker: str, prompt: str, signal):
    """Save an analyst signal to the database."""
    db = get_db()
    if db is None:
        logger.warning("Database not initialized, skipping save_signal")
        return None
    return db.save_signal(portfolio_id, analyst, ticker, prompt, signal)
