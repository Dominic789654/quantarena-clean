from typing import  Dict, Any
from langgraph.graph import StateGraph, START, END
from graph.schema import FundState, Portfolio, Decision, Action, Position
from graph.constants import AgentKey
from agents.registry import AgentRegistry
from agents.planner import planner_agent
from util.db_helper import get_db
from util.logger import logger
from time import perf_counter


class AgentWorkflow:
    """Trading Decision Workflow."""

    def __init__(self, config: Dict[str, Any], config_id: str, market: str = 'us'):
        self.llm_config = config['llm']
        self.tickers = config['tickers']
        self.exp_name = config['exp_name']
        self.trading_date = config['trading_date']
        self.personality = config.get('personality', 'balanced')
        self.api_source = config.get('api_source', {})
        self.market = market
        self.db = get_db()

        # load latest portfolio from DB
        portfolio = self.db.get_latest_portfolio(config_id)
        if not portfolio:
            portfolio = self.db.create_portfolio(config_id, config['cashflow'], config['trading_date'])
            if not portfolio:
                raise RuntimeError(f"Failed to create portfolio for config {self.exp_name}")
        
        # copy portfolio with a new id
        new_portfolio = self.db.copy_portfolio(config_id, portfolio, config['trading_date'])
        self.init_portfolio = Portfolio(**new_portfolio)
        logger.info(f"New portfolio ID: {self.init_portfolio.id}")
        
        # Initialize workflow configuration
        self.planner_mode = config.get('planner_mode', False)
        
        # Verify workflow analysts
        if not config.get('workflow_analysts'):
            raise ValueError("workflow_analysts must be provided in config")
            
        # Validate analysts and remove invalid ones
        self.workflow_analysts = config['workflow_analysts']
        invalid_analysts = [a for a in self.workflow_analysts if not AgentRegistry.check_agent_key(a)]
        if invalid_analysts:
            logger.warning(f"Invalid analyst keys removed: {invalid_analysts}")
            self.workflow_analysts = [a for a in self.workflow_analysts if a not in invalid_analysts]
            
        if not self.workflow_analysts:
            raise ValueError("No valid analysts remaining after validation")


    def build(self) -> StateGraph:
        """Build the workflow"""
        graph = StateGraph(FundState)
        
        # create node for portfolio manager
        portfolio_agent = AgentRegistry.get_agent_func_by_key(AgentKey.PORTFOLIO)
        graph.add_node(AgentKey.PORTFOLIO, portfolio_agent)
        
        # create node for each analyst and add edge
        for analyst in self.current_analysts:
            agent_func = AgentRegistry.get_agent_func_by_key(analyst)
            graph.add_node(analyst, agent_func)
            graph.add_edge(START, analyst)
            graph.add_edge(analyst, AgentKey.PORTFOLIO)
        
        # Route portfolio manager to end
        graph.add_edge(AgentKey.PORTFOLIO, END)
        workflow = graph.compile()

        return workflow 
        

    def load_analysts(self, ticker: str):
        """
        Load the analysts for processing:
        - If planner_mode is True: use planner to select from verified workflow_analysts
        - If planner_mode is False: use all verified workflow_analysts
        """
        if self.planner_mode:
            logger.info("Using planner agent to select analysts from verified list")
            self.current_analysts = planner_agent(ticker, self.llm_config, self.workflow_analysts)
            if not self.current_analysts:
                raise ValueError("No analysts selected by planner")
        else:
            logger.info("Using all verified analysts")
            self.current_analysts = self.workflow_analysts.copy()
            
        logger.info(f"Active analysts for {ticker}: {self.current_analysts}")
    
    def run(self, config_id: str) -> float:
        """Run the workflow."""
        start_time = perf_counter()

        # will be updated by the output of workflow
        portfolio = self.init_portfolio 
        for ticker in self.tickers:
            self.load_analysts(ticker)
            
            # init FundState
            state = FundState(
                ticker = ticker,
                exp_name = self.exp_name,
                trading_date = self.trading_date,
                market = self.market,
                api_source = self.api_source,
                llm_config = self.llm_config,
                portfolio = portfolio,
                num_tickers = len(self.tickers),
                personality = self.personality
            )

            # build the workflow
            workflow = self.build()
            logger.info(f"{ticker} workflow compiled successfully")
            try:
                final_state = workflow.invoke(state)
            except Exception as e:
                logger.error(f"Error running deep fund: {e}")
                raise RuntimeError(f"Failed to generate new portfolio {portfolio.id}")

            # update portfolio
            portfolio = self.update_portfolio_ticker(portfolio, ticker, final_state["decision"])
            logger.log_portfolio(f"{ticker} position update", portfolio)

            if self.planner_mode:
                self.current_analysts = None # clean and reset current_analysts

        logger.log_portfolio("Final Portfolio", portfolio)
        logger.info("Updating portfolio to Database")
        portfolio_dict = portfolio.model_dump()
        self.db.update_portfolio(config_id, portfolio_dict, self.trading_date)

        end_time = perf_counter()
        time_cost = end_time - start_time

        return time_cost


    def update_portfolio_ticker(self, portfolio: Portfolio, ticker: str, decision: Decision) -> Portfolio:
        """Update the ticker asset in the portfolio."""

        action = decision.action
        shares = decision.shares
        price = decision.price

        if ticker not in portfolio.positions:
            portfolio.positions[ticker] = Position(shares=0, value=0)

        if action == Action.BUY:
            portfolio.positions[ticker].shares += shares
            portfolio.cashflow -= price * shares
        elif action == Action.SELL:
            portfolio.positions[ticker].shares -= shares
            portfolio.cashflow += price * shares

        # Always recalculate position value with latest price
        portfolio.positions[ticker].value = round(price * portfolio.positions[ticker].shares, 2)

        # round cashflow
        portfolio.cashflow = round(portfolio.cashflow, 2)

        return portfolio
