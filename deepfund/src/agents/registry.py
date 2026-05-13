from typing import Dict, Callable, List
from agents.analysts import (
    technical_agent,
    insider_agent,
    company_news_agent,
    fundamental_agent,
    macroeconomic_agent,
    policy_agent,
    deepear_intelligence_agent,
)
from agents.portfolio_manager import portfolio_agent
from graph.constants import AgentKey

class AgentRegistry:
    """Registry for all agents."""
    
    # Initialize as actual dictionaries, not just type annotations
    agent_func_mapping: Dict[str, Callable] = {}
    agent_doc_mapping: Dict[str, str] = {}

    # Analyst KEYs
    ANALYST_KEYS = [
        AgentKey.TECHNICAL,
        AgentKey.FUNDAMENTAL,
        AgentKey.INSIDER,
        AgentKey.COMPANY_NEWS,
        AgentKey.MACROECONOMIC,
        AgentKey.POLICY,
        AgentKey.DEEPEAR_INTELLIGENCE
    ]

    @classmethod
    def get_agent_func_by_key(cls, key: str) -> Callable:
        """Get agent function by key."""
        return cls.agent_func_mapping.get(key)

    @classmethod
    def get_all_analyst_keys(cls) -> List[str]:
        """Get all analyst keys."""
        return cls.ANALYST_KEYS
    
    @classmethod
    def check_agent_key(cls, key: str) -> bool:
        """Check if an agent key is valid."""
        return key in cls.ANALYST_KEYS

    @classmethod
    def get_analyst_info(cls, key: str) -> str:
        """Get analyst info."""
        return cls.agent_doc_mapping[key]

    @classmethod
    def register_agent(cls, key: str, agent_func: Callable, agent_doc: str) -> None:
        """
        Register a new agent.
        
        Args:
            key: Unique identifier for the agent
            agent_func: Function that implements the agent logic
            agent_doc: short description of the agent
        """
        cls.agent_func_mapping[key] = agent_func
        cls.agent_doc_mapping[key] = agent_doc

    @classmethod
    def run_registry(cls):
        """Run the registry."""

        cls.register_agent(
            key=AgentKey.PORTFOLIO,
            agent_func=portfolio_agent,
            agent_doc="Portfolio manager making final trading decisions based on the signals from the analysts."
        )

        cls.register_agent(
            key=AgentKey.FUNDAMENTAL,
            agent_func=fundamental_agent,
            agent_doc="Fundamental analysis specialist focusing on company financial health and valuation."
        )

        cls.register_agent(
            key=AgentKey.INSIDER,
            agent_func=insider_agent,
            agent_doc="Insider trading specialist analyzing insider activity patterns."
        )

        cls.register_agent(
            key=AgentKey.COMPANY_NEWS,
            agent_func=company_news_agent,
            agent_doc="Company news specialist analyzing company news and media coverage."
        )
                
        cls.register_agent(
            key=AgentKey.TECHNICAL,
            agent_func=technical_agent,
            agent_doc="Technical analysis specialist using multiple technical analysis strategies."
        )

        cls.register_agent(
            key=AgentKey.MACROECONOMIC,
            agent_func=macroeconomic_agent,
            agent_doc="Macroeconomic analysis specialist focusing on economic indicators, interest rates, inflation and market trends."
        )

        cls.register_agent(
            key=AgentKey.POLICY,
            agent_func=policy_agent,
            agent_doc="Policy analysis specialist focusing on fiscal and monetary policy."
        )

        cls.register_agent(
            key=AgentKey.DEEPEAR_INTELLIGENCE,
            agent_func=deepear_intelligence_agent,
            agent_doc="Intelligence analyst using DeepEar's ISQ framework and multi-source news analysis for A-share market opportunities."
        )
