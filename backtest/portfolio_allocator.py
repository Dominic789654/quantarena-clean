"""
Portfolio Allocator
===================
组合分配器：基于所有股票的分析师信号，统一做出资金分配决策。

这是 B1 方案的核心组件，实现多股票组合层面的统一决策。
"""

import os
import json
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

# Setup project paths using unified path manager
from shared.utils.path_manager import setup_paths
setup_paths()
from shared.config.profile_registry import PROFILE_ALIASES, normalize_profile_name
from shared.utils.macaron_responses import (
    build_ticker_weight_schema,
    call_macaron_json,
    extract_token_usage,
)

from deepear.src.utils.llm.factory import get_model
from agno.agent import Agent

try:
    from llm.inference import record_token_usage
    TOKEN_TRACKER_AVAILABLE = True
except ImportError:
    TOKEN_TRACKER_AVAILABLE = False


@dataclass
class AnalystSignal:
    """分析师信号结构"""
    ticker: str
    signal: str  # "BULLISH", "BEARISH", "NEUTRAL"
    justification: str
    confidence: float = 0.5


@dataclass
class Portfolio:
    """简化组合结构"""
    cashflow: float
    positions: Dict[str, int]  # ticker -> shares


class PortfolioAllocator:
    """
    组合层面的决策 Agent

    输入：多股票的分析师信号 + 当前组合 + 历史决策
    输出：每只股票的目标仓位比例
    """

    PERSONALITY_PROMPTS = {
        "conservative": """
你是一位保守型基金经理（Conservative）。你的投资哲学：
- 资本保全优先，宁可错过机会也不愿承担过大风险
- 单只股票最大仓位不超过 20%
- 倾向于分散投资，现金比例较高
- 对负面信号敏感，会快速减仓
- 追求稳定的绝对收益，不追求超额收益
""",
        "balanced": """
你是一位平衡型基金经理（Balanced）。你的投资哲学：
- 风险与收益平衡，在控制风险的前提下追求增长
- 单只股票最大仓位不超过 33%
- 根据信号质量动态调整仓位
- 既关注基本面也关注技术面
- 适度的交易频率，避免过度交易
""",
        "aggressive": """
你是一位激进型基金经理（Aggressive）。你的投资哲学：
- 追求最大化收益，愿意承担较高风险
- 单只股票最大仓位可达 50%
- 对强烈看涨信号敢于重仓
- 积极捕捉市场机会，交易频率较高
- 止损线设置较宽，能承受短期波动
""",
        "passive": """
你是一位被动型基金经理（Passive）。你的投资哲学：
- 指数跟踪为主，尽量减少主动调仓
- 仓位配置相对固定，变化不大
- 低换手率，长期持有
- 仅在市场发生重大变化时才调整
- 追求市场平均收益（Beta），不追求超额收益（Alpha）
""",
        "fof": """
你是一位母基金型基金经理（FOF, Fund-of-Funds）。你的投资哲学：
- 把每只股票视为多风格 sleeve 组合里的风险预算载体，而不是孤立下注
- 单只股票最大仓位不超过 15%
- 优先保持分散配置、回撤控制与组合韧性
- 信号分歧较大时宁可维持中性仓位，也避免激进集中
- 只有当标的能改善组合平衡与风险收益结构时才明显加仓
""",
        "macro_tactical": """
你是一位宏观战术配置型基金经理（Macro Tactical Allocation）。你的投资哲学：
- 先判断宏观与市场状态，再调整不同风格 sleeve 的风险暴露
- 在风险上升阶段偏向防守和现金缓冲，在顺风阶段适度提高进攻性配置
- 更重视自上而下的风险预算，而不是对单一股票做孤立下注
- 允许动态切换风格权重，但避免无纪律的大幅来回调仓
- 优先关注市场状态变化对组合整体韧性的影响
""",
        "fundamental_value": """
你是一位基本面价值型基金经理（Fundamental Value）。你的投资哲学：
- 优先持有基本面更扎实、估值更合理的公司
- 不追逐短期价格噪音，更看重经营质量与估值纪律
- 倾向于耐心建仓和中低换手
- 当新闻与技术信号缺乏基本面支撑时保持克制
- 更重视长期质量一致性而非短期叙事热度
""",
        "behavioral_momentum": """
你是一位行为动量型基金经理（Behavioral Momentum）。你的投资哲学：
- 追踪趋势延续、情绪强化和市场叙事聚集
- 当技术信号与新闻情绪共振时快速提高配置
- 愿意接受较高换手来捕捉群体行为驱动的行情
- 对趋势反转保持警惕，避免在动量脆弱时过度暴露
- 优先顺势而为，而不是基于静态估值锚做决策
""",
        "equal_weight_index": """
你是一位严格的等权指数跟踪基金经理（Equal-Weight Index Tracker）。你的投资哲学：
- 你的目标是机械地维持每只股票等权（1/N）
- 不做主观择时和选股，不根据短期噪音频繁调仓
- 仅在权重偏离目标时再平衡
- 优先控制跟踪误差，而不是追求主观超额收益
- 允许保留少量现金用于交易执行缓冲
"""
    }
    PERSONALITY_ALIASES = {}
    for _raw_profile, _canonical_profile in PROFILE_ALIASES.items():
        if _canonical_profile in PERSONALITY_PROMPTS:
            PERSONALITY_ALIASES[_raw_profile] = _canonical_profile

    @classmethod
    def _normalize_personality(cls, personality: Optional[str]) -> str:
        """Normalize aliases to canonical personality/profile keys."""
        name = normalize_profile_name(personality)
        if name in cls.PERSONALITY_PROMPTS:
            return name
        return "balanced"

    def __init__(
        self,
        personality: str = "balanced",
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
    ):
        """
        初始化组合分配器

        Args:
            personality: 投资性格 (conservative, balanced, aggressive, passive, fof)
        """
        self.personality = self._normalize_personality(personality)
        self.persona_prompt = self.PERSONALITY_PROMPTS[self.personality]
        self.llm_provider = (llm_provider or os.getenv("REASONING_MODEL_PROVIDER", "ark")).strip().lower()
        self.llm_model = (llm_model or os.getenv("REASONING_MODEL_ID", "kimi-k2.5")).strip()
        logger.info(f"PortfolioAllocator initialized with personality: {self.personality}")

    def allocate(
        self,
        signals: Dict[str, Any],  # Accepts both AnalystSignal and dict
        current_portfolio: Portfolio,
        prices: Dict[str, float],
        trading_date: str,
        decision_memory: Optional[List[Dict]] = None
    ) -> Dict[str, float]:
        """
        做出组合资金分配决策

        Args:
            signals: {ticker: AnalystSignal or dict} 所有股票的分析师信号
            current_portfolio: 当前组合状态
            prices: {ticker: current_price} 当前价格
            trading_date: 交易日期
            decision_memory: 最近的历史决策记录

        Returns:
            {ticker: target_position_ratio} 每只股票的目标仓位比例 (0~1)
        """
        # 构建 prompt
        prompt = self._build_allocation_prompt(
            signals, current_portfolio, prices, trading_date, decision_memory
        )

        # 调用 LLM
        try:
            if self.llm_provider == "macaron":
                allocations = self._allocate_with_macaron(prompt, list(signals.keys()))
            else:
                model = get_model(self.llm_provider, self.llm_model)
                agent = Agent(model=model, markdown=False)
                response = agent.run(prompt)
                allocations = self._parse_allocation(response.content, list(signals.keys()))

            logger.info(f"Portfolio allocation for {trading_date}: {allocations}")
            return allocations

        except Exception as e:
            logger.error(f"Portfolio allocation failed: {e}")
            # 失败时保持当前仓位
            return self._fallback_allocation(signals, current_portfolio, prices)

    def _build_allocation_prompt(
        self,
        signals: Dict[str, Any],
        portfolio: Portfolio,
        prices: Dict[str, float],
        trading_date: str,
        decision_memory: Optional[List[Dict]]
    ) -> str:
        """构建组合分配 prompt"""

        # 计算当前市值
        current_value = portfolio.cashflow
        position_values = {}
        for ticker, shares in portfolio.positions.items():
            if ticker in prices:
                value = shares * prices[ticker]
                position_values[ticker] = value
                current_value += value

        # 构建信号摘要
        signals_text = []
        for ticker, signal in signals.items():
            price = prices.get(ticker, 0)
            current_shares = portfolio.positions.get(ticker, 0)
            current_ratio = (current_shares * price / current_value) if current_value > 0 else 0

            # 处理两种格式：AnalystSignal 对象 或 dict
            if hasattr(signal, 'signal'):
                sig_val = str(signal.signal)
                justification = getattr(signal, 'justification', '')
                confidence = getattr(signal, 'confidence', 0.5)
            else:
                sig_val = signal.get('signal', 'NEUTRAL')
                justification = signal.get('justification', '')
                confidence = signal.get('confidence', 0.5)

            signals_text.append(f"""
【{ticker}】当前价格: ¥{price:.2f}
- 分析师信号: {sig_val} (置信度: {confidence:.2f})
- 分析理由: {justification[:100]}...
- 当前持仓: {current_shares}股 (占比: {current_ratio:.1%})
""")

        # 构建历史决策记忆
        memory_text = ""
        if decision_memory:
            memory_text = "\n【最近交易历史】\n"
            for i, mem in enumerate(decision_memory[-5:], 1):  # 最近 5 次
                memory_text += f"{i}. {mem.get('trading_date', 'N/A')}: {mem.get('action', 'N/A')} {mem.get('ticker', 'N/A')} {mem.get('shares', 0)}股\n"

        prompt = f"""你是一位专业的基金经理，负责管理投资组合。

【你的投资风格】
{self.persona_prompt}

【当前日期】{trading_date}

【组合状态】
- 总资产: ¥{current_value:,.2f}
- 现金: ¥{portfolio.cashflow:,.2f} ({portfolio.cashflow/current_value:.1%})

【股票信号分析】
{''.join(signals_text)}
{memory_text}

【任务】
基于以上信息，为每只股票分配目标仓位比例（0.0 ~ 1.0）。

要求：
1. 所有股票的目标仓位比例之和不超过 1.0（保留部分现金是允许的）
2. 根据你的投资风格（{self.personality}）决定仓位集中度
3. 考虑分析师信号的置信度和方向
4. 参考历史决策，保持策略一致性

请输出严格的 JSON 格式：
```json
{{
  "600519": 0.20,
  "000858": 0.15,
  "601318": 0.10,
  "300750": 0.25,
  "600036": 0.10
}}
```

并简要说明你的配置理由（2-3句话）。
"""
        return prompt

    @staticmethod
    def _normalize_allocations(
        parsed: Any,
        tickers: List[str],
        *,
        require_all_tickers: bool = False,
    ) -> Dict[str, float]:
        """Normalize parsed allocation data into ticker -> [0, 1] weights."""
        if not isinstance(parsed, dict):
            raise ValueError(f"Allocation payload must be an object, got {type(parsed).__name__}")

        if require_all_tickers:
            missing = [ticker for ticker in tickers if ticker not in parsed]
            if missing:
                raise ValueError(
                    "Allocation payload missing required tickers: "
                    + ", ".join(missing)
                )

        allocations: Dict[str, float] = {}
        for ticker in tickers:
            if ticker in parsed:
                ratio = float(parsed[ticker])
                allocations[ticker] = max(0.0, min(1.0, ratio))
            else:
                allocations[ticker] = 0.0

        total = sum(allocations.values())
        if total > 1.0:
            allocations = {ticker: weight / total for ticker, weight in allocations.items()}
        return allocations

    @staticmethod
    def _estimate_tokens(prompt: str, response_text: str = "") -> tuple[int, int]:
        """Best-effort token estimate when provider metadata is unavailable."""
        return max(1, len(prompt or "") // 3), max(1, len(response_text or "") // 3 or 1)

    def _allocate_with_macaron(self, prompt: str, tickers: List[str]) -> Dict[str, float]:
        """Allocate via the Macaron Responses API using strict JSON-schema output."""
        parsed, raw = call_macaron_json(
            prompt,
            build_ticker_weight_schema(tickers),
            schema_name=f"{self.personality}_allocation",
            model=self.llm_model,
            timeout=int(os.getenv("MACARON_TIMEOUT", "120")),
        )
        allocations = self._normalize_allocations(parsed, tickers, require_all_tickers=True)

        if TOKEN_TRACKER_AVAILABLE:
            estimated_input, estimated_output = self._estimate_tokens(prompt, json.dumps(allocations, ensure_ascii=False))
            usage_input, usage_output = extract_token_usage(raw)
            if usage_input > 0:
                estimated_input = usage_input
            if usage_output > 0:
                estimated_output = usage_output
            record_token_usage("portfolio_allocator", estimated_input, estimated_output, self.llm_provider)

        return allocations

    def _parse_allocation(self, content: str, tickers: List[str]) -> Dict[str, float]:
        """解析 LLM 输出的仓位分配"""
        # 尝试提取 JSON
        try:
            # 查找 ```json ... ``` 格式
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接找 JSON 对象
                json_match = re.search(r'\{[\s\S]*?\}', content)
                json_str = json_match.group(0) if json_match else content

            parsed = json.loads(json_str)
            allocations = self._normalize_allocations(parsed, tickers)

        except Exception as e:
            logger.warning(f"Failed to parse allocation from LLM output: {e}")
            logger.warning(f"Raw content: {content[:500]}")
            # 平均分配作为 fallback
            equal_ratio = 1.0 / len(tickers) if tickers else 0.0
            allocations = {ticker: equal_ratio for ticker in tickers}

        return allocations

    def _fallback_allocation(
        self,
        signals: Dict[str, Any],
        portfolio: Portfolio,
        prices: Dict[str, float]
    ) -> Dict[str, float]:
        """失败时的 fallback 分配：保持当前仓位"""
        allocations = {}
        total_value = portfolio.cashflow

        for ticker, shares in portfolio.positions.items():
            if ticker in prices:
                total_value += shares * prices[ticker]

        for ticker in signals.keys():
            shares = portfolio.positions.get(ticker, 0)
            price = prices.get(ticker, 0)
            value = shares * price
            allocations[ticker] = value / total_value if total_value > 0 else 0.0

        return allocations
