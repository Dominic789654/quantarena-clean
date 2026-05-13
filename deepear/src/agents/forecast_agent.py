import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from agno.agent import Agent
from agno.models.base import Model
from loguru import logger

from deepear.src.utils.json_utils import extract_json
from deepear.src.utils.database_manager import DatabaseManager
from deepear.src.schema.models import ForecastResult, KLinePoint, InvestmentSignal
from deepear.src.prompts.forecast_analyst import (
    get_forecast_adjustment_instructions,
    get_forecast_task,
    get_llm_forecast_instructions,
    get_llm_forecast_task
)

# 配置：是否启用 Kronos 模型预测
ENABLE_KRONOS = os.getenv("ENABLE_KRONOS_FORECAST", "false").lower() in ("true", "1", "yes")

# 延迟导入 Kronos（仅在需要时）
_kronos_predictor = None

def _get_kronos_predictor():
    """延迟加载 Kronos 预测器"""
    global _kronos_predictor
    if _kronos_predictor is None:
        try:
            from deepear.src.utils.kronos_predictor import KronosPredictorUtility
            _kronos_predictor = KronosPredictorUtility()
        except Exception as e:
            logger.warning(f"⚠️ Failed to load Kronos: {e}")
            return None
    return _kronos_predictor


class ForecastAgent:
    """
    预测智能体 (ForecastAgent)

    支持两种预测模式：
    1. Kronos 模式：使用 Kronos 时序模型 + LLM 调整
    2. LLM 模式：纯 LLM 基于历史数据和信号进行预测
    """

    def __init__(self, db: DatabaseManager, model: Model):
        self.db = db
        self.model = model
        self.use_kronos = ENABLE_KRONOS

        if self.use_kronos:
            logger.info("🔮 ForecastAgent: Using Kronos model mode")
        else:
            logger.info("🔮 ForecastAgent: Using LLM-only prediction mode")

        # 预测智能体
        self.forecaster = Agent(
            model=self.model,
            instructions=["你是一位专业的量化分析师。"],
            markdown=False,
            debug_mode=True
        )

    def _get_next_trading_days(self, start_date: datetime, n_days: int) -> List[str]:
        """获取接下来的 n 个交易日（简化版，跳过周末）"""
        from pandas.tseries.offsets import BusinessDay

        dates = []
        current = start_date
        while len(dates) < n_days:
            current = current + timedelta(days=1)
            # 跳过周末
            if current.weekday() < 5:
                dates.append(current.strftime("%Y-%m-%d"))
        return dates

    def _format_historical_data(self, df, lookback: int = 20) -> str:
        """格式化历史 K 线数据为字符串"""
        if df.empty:
            return "无历史数据"

        # 取最近 lookback 条
        df_recent = df.tail(lookback)

        lines = ["日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量"]
        lines.append("-" * 50)

        for _, row in df_recent.iterrows():
            date = row.get('date', row.get('trade_date', 'N/A'))
            lines.append(
                f"{date} | {row.get('open', 0):.2f} | {row.get('high', 0):.2f} | "
                f"{row.get('low', 0):.2f} | {row.get('close', 0):.2f} | {row.get('volume', 0):,.0f}"
            )

        return "\n".join(lines)

    def _generate_llm_forecast(
        self,
        ticker: str,
        df,
        signals: List[InvestmentSignal],
        pred_len: int = 5,
        lookback: int = 20
    ) -> Optional[ForecastResult]:
        """
        纯 LLM 预测模式
        """
        logger.info(f"🔮 Generating LLM-only forecast for {ticker}...")

        # 1. 格式化历史数据
        historical_str = self._format_historical_data(df, lookback)

        # 2. 准备信号上下文
        signal_lines = []
        for s in (signals or []):
            try:
                if isinstance(s, dict):
                    title = s.get('title', '')
                    summary = s.get('summary', '')
                    sentiment = s.get('sentiment_score', s.get('isq_scores', {}).get('sentiment', 0.5))
                else:
                    title = getattr(s, 'title', '')
                    summary = getattr(s, 'summary', '')
                    sentiment = getattr(s, 'sentiment_score', 0.5)

                if title:
                    sentiment_label = "利好" if sentiment > 0.6 else "利空" if sentiment < 0.4 else "中性"
                    signal_lines.append(f"- [{sentiment_label}] {title}: {summary[:200]}")
            except Exception:
                continue

        signals_context = "\n".join(signal_lines).strip() or "暂无相关信号"

        # 3. 获取当前价格
        current_price = None
        if not df.empty:
            last_row = df.iloc[-1]
            current_price = last_row.get('close', last_row.get('price', None))

        # 4. 生成预测指令
        instructions = get_llm_forecast_instructions(
            ticker=ticker,
            historical_data=historical_str,
            signals_context=signals_context,
            pred_len=pred_len,
            current_price=current_price
        )

        self.forecaster.instructions = [instructions]

        try:
            response = self.forecaster.run(get_llm_forecast_task())
            content = response.content if hasattr(response, 'content') else str(response)

            forecast_data = extract_json(content)

            if not forecast_data or "forecast" not in forecast_data:
                logger.warning(f"⚠️ LLM forecast parsing failed for {ticker}")
                return None

            # 5. 构建 KLinePoint 列表
            forecast_points = []
            for p in forecast_data["forecast"]:
                try:
                    forecast_points.append(KLinePoint(
                        date=p.get("date", ""),
                        open=float(p.get("open", 0)),
                        high=float(p.get("high", 0)),
                        low=float(p.get("low", 0)),
                        close=float(p.get("close", 0)),
                        volume=float(p.get("volume", 0))
                    ))
                except Exception as e:
                    logger.warning(f"Invalid KLinePoint data: {p}, error: {e}")
                    continue

            if not forecast_points:
                return None

            # 6. 返回预测结果
            rationale = forecast_data.get("rationale", "LLM 综合分析预测")

            # 在 LLM 模式下，base_forecast 和 adjusted_forecast 相同
            return ForecastResult(
                ticker=ticker,
                base_forecast=forecast_points,
                adjusted_forecast=forecast_points,
                rationale=rationale
            )

        except Exception as e:
            logger.error(f"❌ LLM forecast error for {ticker}: {e}")
            return None

    def _generate_kronos_forecast(
        self,
        ticker: str,
        df,
        signals: List[InvestmentSignal],
        pred_len: int = 5,
        lookback: int = 20
    ) -> Optional[ForecastResult]:
        """
        Kronos 模型预测模式（原有逻辑）
        """
        predictor_util = _get_kronos_predictor()
        if predictor_util is None:
            logger.warning(f"⚠️ Kronos not available, falling back to LLM for {ticker}")
            return self._generate_llm_forecast(ticker, df, signals, pred_len, lookback)

        # ... 原有 Kronos 逻辑 ...
        effective_lookback = lookback
        if len(df) < lookback:
            if len(df) < 10:
                logger.warning(f"⚠️ Not enough history for {ticker}")
                return None
            effective_lookback = len(df)

        # 准备信号上下文
        signal_lines = []
        for s in (signals or []):
            try:
                if isinstance(s, dict):
                    title = s.get('title', '')
                    summary = s.get('summary', '')
                else:
                    title = getattr(s, 'title', '')
                    summary = getattr(s, 'summary', '')
                if title or summary:
                    signal_lines.append(f"- {title}: {summary}")
            except Exception:
                continue

        signals_context = "\n".join(signal_lines).strip()

        # Kronos 预测
        tech_points = predictor_util.get_base_forecast(df, lookback=effective_lookback, pred_len=pred_len, news_text=None)

        news_points = []
        if signals_context:
            news_points = predictor_util.get_base_forecast(df, lookback=effective_lookback, pred_len=pred_len, news_text=signals_context)

        if not tech_points:
            logger.warning(f"⚠️ Failed to get base forecast for {ticker}")
            return None

        has_news_forecast = False
        if news_points and news_points != tech_points:
            has_news_forecast = True
        else:
            news_points = tech_points

        # LLM 调整
        ctx_parts = []
        if signals_context:
            ctx_parts.append("【相关结构化信号摘要】\n" + signals_context)

        if has_news_forecast:
            news_forecast_str = "\n".join([f"Day {i+1}: Open={p.open:.2f}, Close={p.close:.2f}" for i, p in enumerate(news_points)])
            ctx_parts.append(f"【Kronos模型定量修正预测】\n{news_forecast_str}")

        final_context = "\n\n".join(ctx_parts).strip() or "（无额外上下文）"

        adjust_instructions = get_forecast_adjustment_instructions(ticker, final_context, tech_points)
        self.forecaster.instructions = [adjust_instructions]

        try:
            response = self.forecaster.run(get_forecast_task())
            content = response.content if hasattr(response, 'content') else str(response)
            adjust_data = extract_json(content)

            if adjust_data and "adjusted_forecast" in adjust_data:
                final_points = [KLinePoint(**p) for p in adjust_data["adjusted_forecast"]]
                rationale = adjust_data.get("rationale", "LLM 调整预测")

                return ForecastResult(
                    ticker=ticker,
                    base_forecast=tech_points,
                    adjusted_forecast=final_points,
                    rationale=rationale
                )
            elif has_news_forecast:
                return ForecastResult(
                    ticker=ticker,
                    base_forecast=tech_points,
                    adjusted_forecast=news_points,
                    rationale="使用 Kronos News-Aware 模型预测"
                )
            else:
                return ForecastResult(
                    ticker=ticker,
                    base_forecast=tech_points,
                    adjusted_forecast=tech_points,
                    rationale="Kronos 技术面预测"
                )

        except Exception as e:
            logger.error(f"❌ Kronos forecast error for {ticker}: {e}")
            return ForecastResult(
                ticker=ticker,
                base_forecast=tech_points,
                adjusted_forecast=tech_points,
                rationale=f"预测出错: {e}"
            )

    def generate_forecast(
        self,
        ticker: str,
        signals: List[InvestmentSignal],
        lookback: int = 20,
        pred_len: int = 5,
        extra_context: str = "",
    ) -> Optional[ForecastResult]:
        """
        生成预测（自动选择模式）
        """
        logger.info(f"🔮 Generating forecast for {ticker} (mode: {'Kronos' if self.use_kronos else 'LLM'})...")

        # 1. 获取历史数据
        from deepear.src.utils.stock_tools import StockTools
        stock_tools = StockTools(self.db, auto_update=False)

        import pandas as pd
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - pd.Timedelta(days=max(lookback * 4, 90))).strftime("%Y-%m-%d")
        df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date)

        if df.empty or len(df) < 10:
            logger.warning(f"⚠️ Not enough history for {ticker}, trying network sync...")
            df = stock_tools.get_stock_price(ticker, start_date=start_date, end_date=end_date, force_sync=True)

        if df.empty:
            logger.warning(f"⚠️ No history data for {ticker}")
            return None

        # 2. 根据配置选择预测模式
        if self.use_kronos:
            return self._generate_kronos_forecast(ticker, df, signals, pred_len, lookback)
        else:
            return self._generate_llm_forecast(ticker, df, signals, pred_len, lookback)
