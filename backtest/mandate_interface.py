"""Shared interface for mandate-level allocation policies."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class MandateAllocator(Protocol):
    """Protocol for portfolio-level mandate allocators.

    Implementations convert current signals and portfolio state into target
    position weights. The execution harness remains responsible for translating
    those weights into trades and accounting updates.
    """

    def allocate(
        self,
        signals: Dict[str, Any],
        current_portfolio: Any,
        prices: Dict[str, float],
        trading_date: str,
        decision_memory: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, float]:
        """Return target position weights keyed by ticker."""
        ...


def allocate_with_mandate(
    allocator: MandateAllocator,
    *,
    signals: Dict[str, Any],
    current_portfolio: Any,
    prices: Dict[str, float],
    trading_date: str,
    decision_memory: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Call a mandate allocator through the shared policy interface."""
    return allocator.allocate(
        signals=signals,
        current_portfolio=current_portfolio,
        prices=prices,
        trading_date=trading_date,
        decision_memory=decision_memory,
    )
