"""Reconciliation helpers for broker and local portfolio state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .broker import AccountSnapshot, BrokerPosition


@dataclass(frozen=True)
class ReconciliationDifference:
    """One broker/local state mismatch."""

    kind: str
    symbol: str | None
    expected: float | int
    actual: float | int


@dataclass(frozen=True)
class ReconciliationReport:
    """Result of comparing expected local state with broker state."""

    ok: bool
    differences: tuple[ReconciliationDifference, ...]


def reconcile_account(
    *,
    expected_cash: float,
    expected_positions: Mapping[str, int],
    account: AccountSnapshot,
    positions: list[BrokerPosition] | tuple[BrokerPosition, ...],
    cash_tolerance: float = 1e-6,
) -> ReconciliationReport:
    """Compare expected local cash/positions with broker snapshots."""
    differences: list[ReconciliationDifference] = []
    if abs(float(expected_cash) - float(account.cash)) > cash_tolerance:
        differences.append(
            ReconciliationDifference(
                kind="cash",
                symbol=None,
                expected=float(expected_cash),
                actual=float(account.cash),
            )
        )

    expected = {
        symbol.strip().upper(): int(shares)
        for symbol, shares in expected_positions.items()
        if symbol.strip() and int(shares) != 0
    }
    actual = {
        position.symbol.strip().upper(): int(position.shares)
        for position in positions
        if int(position.shares) != 0
    }
    for symbol in sorted(set(expected) | set(actual)):
        expected_shares = expected.get(symbol, 0)
        actual_shares = actual.get(symbol, 0)
        if expected_shares != actual_shares:
            differences.append(
                ReconciliationDifference(
                    kind="position",
                    symbol=symbol,
                    expected=expected_shares,
                    actual=actual_shares,
                )
            )

    return ReconciliationReport(ok=not differences, differences=tuple(differences))
