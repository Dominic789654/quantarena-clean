import os
import sqlite3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_db_path():
    """Get the database path from environment variable (dynamic)."""
    db_path = os.getenv("DB_PATH", "data/deepfund.db")
    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return db_path


# For backwards compatibility, expose DB_PATH as a property-like variable
class DBPathProxy:
    """Proxy class to make DB_PATH dynamic."""
    def __str__(self):
        return get_db_path()

    def __repr__(self):
        return get_db_path()

    def __fspath__(self):
        return get_db_path()


DB_PATH = DBPathProxy()

def init_database():
    """Initialize the SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
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
        justification TEXT NOT NULL ,
        FOREIGN KEY (portfolio_id) REFERENCES portfolio(id)
    )
    ''')

    # Create indices for better query performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_config_exp_name ON config(exp_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_updated ON portfolio(updated_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_portfolio_trading_date ON portfolio(trading_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision_portfolio ON decision(portfolio_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision_updated ON decision(updated_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_decision_trading_date ON decision(trading_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_portfolio ON signal(portfolio_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_updated ON signal(updated_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_analyst ON signal(analyst)')
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_database()
    print(f"Database initialized at {DB_PATH}") 