from graph.constants import AgentKey, Action
from llm.prompt import (
    get_portfolio_prompt,
    get_risk_control_prompt,
)
from agents.personalities import get_personality
from graph.schema import Decision, FundState, PositionRisk
from llm.inference import agent_call
from apis.router import Router, resolve_api_source
from util.db_helper import get_db
from util.logger import logger

# Portfolio Manager Thresholds
thresholds = {
    "decision_memory_limit": 5
}


def resolve_max_position_ratio(personality: str, num_tickers: int) -> float:
    """Resolve the effective position cap using personality and diversification rules."""
    personality_cap = float(get_personality(personality).get("max_position_ratio", 1.0))
    diversification_cap = 1.0
    if num_tickers > 1:
        diversification_cap = round(2 / num_tickers * 20) / 20
    return max(0.0, min(personality_cap, diversification_cap))


def portfolio_agent(state: FundState):
    """Makes final trading decisions and generates orders"""
    agent_name = AgentKey.PORTFOLIO
    portfolio = state["portfolio"]
    ticker = state["ticker"]
    exp_name = state["exp_name"]
    trading_date = state["trading_date"]
    analyst_signals = state["analyst_signals"]
    llm_config = state["llm_config"]
    num_tickers = state["num_tickers"]
    personality = state.get("personality", "balanced")

    # Get database instance
    db = get_db()

    # Get price data - prefer backtest-provided cached price when available.
    market = state.get("market", "us")
    current_price = state.get("current_price")
    if current_price is None:
        try:
            api_source = resolve_api_source(market, state.get("api_source"))
            router = Router(api_source)
            if market == "cn":
                current_price = router.get_cn_stock_last_close_price(ticker=ticker, trading_date=trading_date)
            else:
                current_price = router.get_us_stock_last_close_price(ticker=ticker, trading_date=trading_date)
        except Exception as e:
            logger.error(f"Failed to fetch price data for {ticker}: {e}")
            raise RuntimeError(f"Failed to make decision")

    # calculate the max position ratio
    max_position_ratio = resolve_max_position_ratio(personality, num_tickers)

    # risk control - use personality-based prompt
    risk_control_prompt_template = get_risk_control_prompt(personality)
    # Generate smart_beta context if needed
    smart_beta_context = ""
    if "smart_beta" in personality.lower():
        smart_beta_context = f"""### Smart Beta Context
- Portfolio volatility: {portfolio.get('volatility', 0.15):.4f}
- Sector diversification: {portfolio.get('sector_count', 3)} sectors
- Current allocation strategy: Quantitative factor-based"""
    risk_prompt = risk_control_prompt_template.format(
        ticker_signals=analyst_signals,
        portfolio=portfolio.model_dump_json(),
        max_position_ratio=max_position_ratio,
        smart_beta_context=smart_beta_context,
    )

    position_risk = agent_call(
        prompt=risk_prompt,
        llm_config=llm_config,
        pydantic_model=PositionRisk,
        agent_name="risk_control"
    )

    logger.log_agent_status(agent_name, ticker, "Risk control")
    logger.log_risk(ticker, position_risk)

    # verify the position ratio if it is in the range
    if position_risk.optimal_position_ratio > max_position_ratio:
        # too bullish, set to the max
        position_risk.optimal_position_ratio = max_position_ratio
    elif position_risk.optimal_position_ratio < 0:
        # too bearish, set to 0
        position_risk.optimal_position_ratio = 0

    logger.log_agent_status(agent_name, ticker, "Making trading decisions")

    # Get decision memory
    decision_memory = db.get_decision_memory(exp_name, ticker, thresholds["decision_memory_limit"])
    current_shares, tradable_shares = calculate_ticker_shares(portfolio, current_price, ticker, position_risk.optimal_position_ratio)

    # Format analyst signals summary for portfolio manager
    analyst_signals_summary = format_analyst_signals_summary(analyst_signals)

    # make trading decision - use personality-based prompt
    portfolio_prompt_template = get_portfolio_prompt(personality)
    prompt = portfolio_prompt_template.format(
        analyst_signals_summary=analyst_signals_summary,
        optimal_position_ratio=position_risk.optimal_position_ratio,
        risk_justification=position_risk.justification,
        decision_memory=decision_memory,
        current_price=current_price,
        current_shares=current_shares,
        tradable_shares=tradable_shares,
        smart_beta_context=smart_beta_context,
    )

    # Generate the trading decision
    ticker_decision = agent_call(
        prompt=prompt,
        llm_config=llm_config,
        pydantic_model=Decision,
        agent_name="portfolio_manager"
    )

    # post-process the decision due to possible reasoning error
    ticker_decision.price = current_price
    if ticker_decision.shares < 0 and ticker_decision.action == Action.SELL:
        ticker_decision.shares = -ticker_decision.shares

    # save decision
    logger.log_decision(ticker, ticker_decision)
    db.save_decision(portfolio.id, ticker, prompt, ticker_decision, trading_date)

    return {"decision": ticker_decision}


def format_analyst_signals_summary(analyst_signals) -> str:
    """Format analyst signals into a readable summary for the portfolio manager."""
    if not analyst_signals:
        return "No analyst signals available."

    summary_parts = []
    for i, signal in enumerate(analyst_signals):
        if hasattr(signal, 'signal') and hasattr(signal, 'justification'):
            # AnalystSignal object
            signal_type = str(signal.signal) if signal.signal else "Unknown"
            justification = signal.justification or "No justification provided"
            summary_parts.append(f"Signal {i+1}: {signal_type}\n  Reason: {justification}")
        elif isinstance(signal, dict):
            # Dict format
            signal_type = signal.get('signal', 'Unknown')
            justification = signal.get('justification', 'No justification provided')
            summary_parts.append(f"Signal {i+1}: {signal_type}\n  Reason: {justification}")
        else:
            summary_parts.append(f"Signal {i+1}: {str(signal)}")

    return "\n\n".join(summary_parts) if summary_parts else "No analyst signals available."


def calculate_ticker_shares(portfolio, current_price, ticker, optimal_position_ratio):
    """calculate the tradable shares for a given ticker based on portfolio"""

    # Get current position value (0 if no position exists)
    current_shares = 0 
    if ticker in portfolio.positions:
        current_shares = portfolio.positions[ticker].shares
    # current value for the ticker
    current_value = current_shares * current_price
    # total portfolio value
    total_portfolio_value = portfolio.cashflow + sum(portfolio.positions[t].value for t in portfolio.positions)
    # position limit for the ticker
    position_limit = total_portfolio_value * optimal_position_ratio
    # position value gap
    position_value_gap = position_limit - current_value

    if position_value_gap > 0: # still have room to buy, maximum tradable cash is the minor between position_value_gap and cashflow
        tradable_shares = min(position_value_gap, portfolio.cashflow) // current_price
    else: # need to sell, maximun selling shares is the minor between position gap and current shares
        tradable_shares = max(position_value_gap // current_price, -current_shares)
    
    return current_shares, tradable_shares
        

    
