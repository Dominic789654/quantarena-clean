import argparse
from typing import Dict, Any
from dotenv import load_dotenv
from graph.workflow import AgentWorkflow
from util.config import ConfigParser
from util.logger import logger
from util.db_helper import db_initialize, get_db

# Load environment variables from .env file
load_dotenv()

def load_portfolio_config(cfg: Dict[str, Any], db):
    """Load and validate config based on experiment configuration."""
    config_id = db.get_config_id_by_name(cfg["exp_name"])
    if not config_id:
        logger.info(f"Creating new config for {cfg['exp_name']}")
        config_id = db.create_config(cfg)
        if not config_id:
            raise RuntimeError(f"Failed to create config for {cfg['exp_name']}")
    return config_id

def main():
    """Main entry point for the DeepFund System."""

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run the DeepFund System")
    parser.add_argument("--config", type=str, required=True, help="Path to configuration file")
    parser.add_argument("--trading-date", type=str, required=True, help="Trading date in format YYYY-MM-DD")
    parser.add_argument("--local-db", action="store_true", help="Use local SQLite database")
    args = parser.parse_args()

    cfg = ConfigParser(args).get_config()

    # Initialize the global database connection based on the local-db flag
    db_initialize(use_local_db=args.local_db)
    db = get_db()
    logger.info(f"Loading config for {cfg['exp_name']}, trading date: {args.trading_date}")
    config_id = load_portfolio_config(cfg, db)
    logger.info("Init DeepFund and run")

    # make sure trading date is in chronological order in DB portfolio table
    latest_trading_date = db.get_latest_trading_date(config_id)
    if latest_trading_date and latest_trading_date > cfg["trading_date"]:
        raise RuntimeError(f"Trading date {args.trading_date} is not in chronological order based on current experiment {cfg['exp_name']}")
    
    # Extract market from config (default to 'us' for backward compatibility)
    market = cfg.get('trading', {}).get('market', 'us').lower()
    logger.info(f"Market: {market}")

    try:
        app = AgentWorkflow(cfg, config_id, market)
        time_cost = app.run(config_id)
        logger.info(f"DeepFund run completed in {time_cost:.2f} seconds")
    except Exception as e:
        logger.error(f"Error during portfolio operations: {e}")
        raise


if __name__ == "__main__":
    main()
