"""
Portfolio Tracker for Backtesting
=================================

Tracks portfolio state and trade history during backtesting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger


@dataclass
class Trade:
    """Represents a single trade execution."""

    date: str
    ticker: str
    action: str  # "BUY" or "SELL"
    shares: int
    price: float
    value: float = field(init=False)
    justification: str = ""

    def __post_init__(self) -> None:
        self.value = round(self.shares * self.price, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Dict form used by tests/serialization."""
        return {
            "date": self.date,
            "ticker": self.ticker,
            "action": self.action,
            "shares": self.shares,
            "price": self.price,
            "value": self.value,
            "justification": self.justification,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


@dataclass
class DailySnapshot:
    """Represents portfolio state at the end of a trading day."""

    date: str
    cashflow: float
    positions: Dict[str, Dict[str, float]]  # {ticker: {"shares": int, "value": float}}
    total_value: float
    daily_return: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization/compatibility."""
        return {
            "date": self.date,
            "cashflow": self.cashflow,
            "positions": self.positions,
            "total_value": self.total_value,
            "daily_return": self.daily_return,
            "return_pct": self.daily_return,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


class PortfolioTracker:
    """
    Tracks portfolio state and trade history during backtesting.

    Maintains:
    - Daily snapshots of portfolio value
    - Trade execution history
    - Position tracking across tickers
    """

    def __init__(
        self,
        initial_cash: float = 100000.0,
        initial_capital: Optional[float] = None,
        tickers: Optional[List[str]] = None,
    ):
        """
        Initialize portfolio tracker.

        Args:
            initial_cash: Starting cash amount (current API)
            initial_capital: Backward-compatible alias for initial_cash
            tickers: Optional ticker list for initializing zero-share positions
        """
        if initial_capital is not None:
            initial_cash = float(initial_capital)

        self.initial_cash = float(initial_cash)
        self.initial_capital = self.initial_cash  # compatibility alias
        self.cash = self.initial_cash
        self.positions: Dict[str, Dict[str, float]] = {
            ticker: {"shares": 0, "value": 0.0} for ticker in (tickers or [])
        }

        self.snapshots: List[DailySnapshot] = []
        self.trades: List[Trade] = []
        self._prev_total_value = self.initial_cash

        logger.info(f"PortfolioTracker initialized with ${self.initial_cash:,.2f}")

    def _default_trade_date(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _position_value(self, ticker: str, price: float) -> float:
        shares = int(self.positions.get(ticker, {}).get("shares", 0))
        return round(shares * price, 2)

    def _positions_with_prices(self, prices: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        data: Dict[str, Dict[str, float]] = {}
        for ticker, pos in self.positions.items():
            shares = int(pos.get("shares", 0))
            if shares <= 0:
                continue
            price = float(prices.get(ticker, pos.get("last_price", 0.0)))
            data[ticker] = {
                "shares": shares,
                "value": round(shares * price, 2),
                "last_price": price,
            }
        return data

    def record_snapshot(
        self,
        date: str,
        cashflow_or_prices: Any,
        positions: Optional[Dict[str, Dict[str, Any]]] = None,
        prices: Optional[Dict[str, float]] = None,
    ) -> DailySnapshot:
        """
        Record a daily portfolio snapshot.

        Supports both signatures:
        - record_snapshot(date, cashflow, positions, prices)      # current API
        - record_snapshot(date, prices)                           # legacy API
        """
        if positions is None and prices is None and isinstance(cashflow_or_prices, dict):
            prices = cashflow_or_prices
            cashflow = self.cash
            positions = self._positions_with_prices(prices)
        else:
            cashflow = float(cashflow_or_prices)
            positions = positions or {}
            prices = prices or {}
            self.cash = cashflow
            self.positions = {
                ticker: {
                    "shares": int(pos.get("shares", 0)),
                    "value": float(pos.get("value", 0.0)),
                    "last_price": float(prices.get(ticker, pos.get("value", 0.0) / max(pos.get("shares", 1), 1))),
                }
                for ticker, pos in positions.items()
            }

        # Ensure position value is price-driven when price exists.
        position_value = 0.0
        normalized_positions: Dict[str, Dict[str, float]] = {}
        for ticker, pos in positions.items():
            shares = int(pos.get("shares", 0))
            if shares <= 0:
                continue
            market_price = float(prices.get(ticker, pos.get("last_price", 0.0)))
            if market_price > 0:
                value = round(shares * market_price, 2)
            else:
                value = round(float(pos.get("value", 0.0)), 2)
            normalized_positions[ticker] = {
                "shares": shares,
                "value": value,
                "last_price": market_price,
            }
            position_value += value

        total_value = cashflow + position_value

        if self._prev_total_value > 0:
            daily_return = (total_value - self._prev_total_value) / self._prev_total_value * 100
        else:
            daily_return = 0.0

        snapshot = DailySnapshot(
            date=date,
            cashflow=round(cashflow, 2),
            positions=normalized_positions,
            total_value=round(total_value, 2),
            daily_return=round(daily_return, 4),
        )

        self.snapshots.append(snapshot)
        self._prev_total_value = total_value

        logger.debug(
            f"Snapshot {date}: Total=${total_value:,.2f}, "
            f"Return={daily_return:+.2f}%, Cash=${cashflow:,.2f}"
        )

        return snapshot

    def record_trade(self, *args: Any, **kwargs: Any) -> Trade:
        """
        Record a trade execution.

        Supports both signatures:
        - record_trade(date, ticker, action, shares, price, justification="")
        - record_trade(action, shares, ticker, price)
        - record_trade(action="BUY", shares=10, ticker="AAPL", price=150.0)
        """
        if args and isinstance(args[0], str) and args[0].upper() in {"BUY", "SELL"}:
            # Legacy style: action, shares, ticker, price
            action = args[0]
            shares = int(args[1])
            ticker = args[2]
            price = float(args[3])
            date = kwargs.get("date", self._default_trade_date())
            justification = kwargs.get("justification", "")
        elif args:
            # Current positional style: date, ticker, action, shares, price, ...
            if len(args) < 5:
                raise ValueError("record_trade requires at least 5 positional args in current mode")
            date = args[0]
            ticker = args[1]
            action = args[2]
            shares = int(args[3])
            price = float(args[4])
            justification = args[5] if len(args) > 5 else kwargs.get("justification", "")
        else:
            # Keyword style
            date = kwargs.get("date", self._default_trade_date())
            ticker = kwargs["ticker"]
            action = kwargs["action"]
            shares = int(kwargs["shares"])
            price = float(kwargs["price"])
            justification = kwargs.get("justification", "")

        if price < 0:
            raise ValueError("Trade price cannot be negative")
        if shares < 0:
            raise ValueError("Trade shares cannot be negative")

        action = action.upper()
        executed_shares = shares
        current = self.positions.get(ticker, {"shares": 0, "value": 0.0, "last_price": price})
        current_shares = int(current.get("shares", 0))

        if action == "BUY":
            self.cash -= shares * price
            new_shares = current_shares + shares
            self.positions[ticker] = {
                "shares": new_shares,
                "value": round(new_shares * price, 2),
                "last_price": price,
            }
        elif action == "SELL":
            executed_shares = min(shares, current_shares)
            self.cash += executed_shares * price
            new_shares = max(current_shares - executed_shares, 0)
            if new_shares == 0:
                self.positions.pop(ticker, None)
            else:
                self.positions[ticker] = {
                    "shares": new_shares,
                    "value": round(new_shares * price, 2),
                    "last_price": price,
                }
        else:
            raise ValueError(f"Unsupported trade action: {action}")

        trade = Trade(
            date=str(date),
            ticker=ticker,
            action=action,
            shares=executed_shares,
            price=price,
            justification=justification,
        )
        self.trades.append(trade)

        logger.info(
            f"Trade recorded: {action} {executed_shares} {ticker} @ ${price:.2f} "
            f"(Value: ${trade.value:,.2f})"
        )

        return trade

    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Legacy helper: current cash + mark-to-market position value."""
        return round(self.cash + sum(self.get_position_value(t, p) for t, p in prices.items()), 2)

    def get_return_pct(self, total_value: float) -> float:
        """Legacy helper: return percentage relative to initial capital."""
        if self.initial_capital <= 0:
            return 0.0
        return round((total_value - self.initial_capital) / self.initial_capital * 100, 2)

    def get_position_value(self, ticker: str, price: float) -> float:
        """Legacy helper: position market value for a ticker."""
        return self._position_value(ticker, price)

    def get_trade_summary(self) -> Dict[str, Any]:
        """Legacy helper: compact trade statistics."""
        return {
            "total_trades": self.get_trade_count(),
            "buy_trades": self.get_buy_count(),
            "sell_trades": self.get_sell_count(),
            "tickers_traded": sorted({t.ticker for t in self.trades}),
        }

    def get_state(self) -> Dict[str, Any]:
        """Serialize tracker state for checkpointing/tests."""
        return {
            "initial_capital": self.initial_capital,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "positions": {k: v.copy() for k, v in self.positions.items()},
            "trades": [t.to_dict() for t in self.trades],
            "snapshots": [s.to_dict() for s in self.snapshots],
            "prev_total_value": self._prev_total_value,
        }

    @classmethod
    def from_state(cls, state: Dict[str, Any]) -> "PortfolioTracker":
        """Restore a tracker from serialized state."""
        tracker = cls(initial_cash=float(state.get("initial_cash", state.get("initial_capital", 100000.0))))
        tracker.cash = float(state.get("cash", tracker.initial_cash))
        tracker.positions = {
            ticker: {
                "shares": int(pos.get("shares", 0)),
                "value": float(pos.get("value", 0.0)),
                "last_price": float(pos.get("last_price", 0.0)),
            }
            for ticker, pos in state.get("positions", {}).items()
        }

        tracker.trades = [
            Trade(
                date=str(t.get("date", tracker._default_trade_date())),
                ticker=str(t.get("ticker", "")),
                action=str(t.get("action", "HOLD")).upper(),
                shares=int(t.get("shares", 0)),
                price=float(t.get("price", 0.0)),
                justification=str(t.get("justification", "")),
            )
            for t in state.get("trades", [])
        ]

        tracker.snapshots = [
            DailySnapshot(
                date=str(s.get("date", "")),
                cashflow=float(s.get("cashflow", 0.0)),
                positions=s.get("positions", {}),
                total_value=float(s.get("total_value", 0.0)),
                daily_return=float(s.get("daily_return", s.get("return_pct", 0.0))),
            )
            for s in state.get("snapshots", [])
        ]
        tracker._prev_total_value = float(state.get("prev_total_value", tracker.initial_cash))
        return tracker

    def get_equity_curve(self) -> pd.DataFrame:
        """
        Get equity curve as DataFrame.

        Returns:
            DataFrame with columns: date, total_value, daily_return, cashflow
        """
        if not self.snapshots:
            return pd.DataFrame(columns=["date", "total_value", "daily_return", "cashflow"])

        data = [s.to_dict() for s in self.snapshots]
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        return df[["date", "total_value", "daily_return", "cashflow"]]

    def get_trades(self) -> List[Trade]:
        """Get all recorded trades."""
        return self.trades.copy()

    def get_trades_df(self) -> pd.DataFrame:
        """
        Get trades as DataFrame.

        Returns:
            DataFrame with columns: date, ticker, action, shares, price, value
        """
        if not self.trades:
            return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "value"])

        df = pd.DataFrame([t.to_dict() for t in self.trades])
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def get_trade_count(self) -> int:
        """Get total number of trades."""
        return len(self.trades)

    def get_buy_count(self) -> int:
        """Get number of buy trades."""
        return len([t for t in self.trades if t.action == "BUY"])

    def get_sell_count(self) -> int:
        """Get number of sell trades."""
        return len([t for t in self.trades if t.action == "SELL"])

    def calculate_avg_position_days(self) -> float:
        """Calculate weighted average holding days for closed shares using FIFO lots."""
        if not self.trades:
            return 0.0

        open_lots: Dict[str, List[Dict[str, Any]]] = {}
        total_share_days = 0
        total_closed_shares = 0

        sorted_trades = sorted(
            self.trades,
            key=lambda trade: (str(trade.date), 0 if trade.action == "BUY" else 1),
        )

        for trade in sorted_trades:
            if trade.shares <= 0:
                continue

            try:
                trade_date = datetime.fromisoformat(str(trade.date))
            except ValueError:
                logger.debug(f"Skipping avg_position_days calculation for invalid trade date: {trade.date}")
                continue

            ticker_lots = open_lots.setdefault(trade.ticker, [])
            if trade.action == "BUY":
                ticker_lots.append({"date": trade_date, "shares": trade.shares})
                continue

            if trade.action != "SELL":
                continue

            remaining_shares = trade.shares
            while remaining_shares > 0 and ticker_lots:
                lot = ticker_lots[0]
                matched_shares = min(remaining_shares, int(lot["shares"]))
                holding_days = max((trade_date - lot["date"]).days, 0)
                total_share_days += holding_days * matched_shares
                total_closed_shares += matched_shares
                lot["shares"] -= matched_shares
                remaining_shares -= matched_shares
                if lot["shares"] <= 0:
                    ticker_lots.pop(0)

        if total_closed_shares == 0:
            return 0.0

        return round(total_share_days / total_closed_shares, 2)

    def get_position_summary(self) -> Dict[str, Dict[str, float]]:
        """
        Get current position summary from last snapshot.

        Returns:
            Dict of {ticker: {"shares": int, "value": float}}
        """
        if self.snapshots:
            return self.snapshots[-1].positions.copy()
        return {k: v.copy() for k, v in self.positions.items()}

    def get_summary(self) -> Dict[str, Any]:
        """
        Get portfolio summary statistics.

        Returns:
            Dict with summary statistics
        """
        if not self.snapshots:
            final_value = self.cash
            total_return = self.get_return_pct(final_value)
            return {
                "initial_cash": self.initial_cash,
                "final_value": round(final_value, 2),
                "total_return": total_return,
                "total_trades": 0,
                "buy_trades": 0,
                "sell_trades": 0,
                "trading_days": 0,
                "final_cash": round(self.cash, 2),
                "final_positions": self.positions.copy(),
            }

        final = self.snapshots[-1]
        total_return = (final.total_value - self.initial_cash) / self.initial_cash * 100

        return {
            "initial_cash": self.initial_cash,
            "final_value": final.total_value,
            "total_return": round(total_return, 2),
            "total_trades": self.get_trade_count(),
            "buy_trades": self.get_buy_count(),
            "sell_trades": self.get_sell_count(),
            "trading_days": len(self.snapshots),
            "final_cash": final.cashflow,
            "final_positions": final.positions,
        }

    def clear(self) -> None:
        """Clear all recorded data."""
        self.snapshots.clear()
        self.trades.clear()
        self.positions.clear()
        self.cash = self.initial_cash
        self._prev_total_value = self.initial_cash
        logger.info("Portfolio tracker cleared")
