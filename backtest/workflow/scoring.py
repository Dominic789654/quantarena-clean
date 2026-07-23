"""Signal-scoring and prioritization helpers for the smart-priority phase
of the backtest workflow adapter.

Ported from `BacktestWorkflowAdapter` instance/static methods by the
extract-workflow-scoring-functions change
(docs/refactor_program_plan.md Phase 3). `_signal_label` and
`_aggregate_signal_from_summary` moved verbatim (they were already
`@staticmethod`s with no instance-state dependency). `
_calculate_priority_score` and `_calculate_signal_consistency` are
ported from instance methods; every internal `self._signal_label(...)`
call becomes a direct call to the module-level `_signal_label(...)`
below (the one mandated non-verbatim rewrite). `_get_smart_priority_order`
is ported from an instance method whose only instance-state read
(`self.tickers.copy()` in the empty-input fallback) becomes an explicit
`tickers` parameter.

`backtest/workflow_adapter.py` keeps same-named delegator methods on
`BacktestWorkflowAdapter` for all five names so every existing
`adapter.<name>(...)` call and instance-attribute monkeypatch keeps
working.
"""

from typing import Any, Dict, List

from loguru import logger


def _signal_label(signal: Any) -> str:
    """Normalize signal enum/string to uppercase label."""
    return str(getattr(signal, "signal", "NEUTRAL")).strip().upper()


def _aggregate_signal_from_summary(summary: Dict[str, Any]) -> str:
    """Collapse analyst counts into a single portfolio-level signal label."""
    bullish_count = int(summary.get("bullish_count", 0) or 0)
    bearish_count = int(summary.get("bearish_count", 0) or 0)

    if bullish_count > bearish_count:
        return "BULLISH"
    if bearish_count > bullish_count:
        return "BEARISH"
    return "NEUTRAL"


def _calculate_priority_score(analyst_signals: List[Any]) -> float:
    """
    Calculate priority score for smart sorting.

    Scoring rules:
    1. Signal strength: BULLISH=3, NEUTRAL=2, BEARISH=1
    2. Weighted by confidence
    3. Higher for signal consistency
    4. Bonus for strong bullish consensus
    """
    if not analyst_signals:
        return 0.0

    # Signal mapping
    SIGNAL_SCORE = {
        "BULLISH": 3.0,
        "NEUTRAL": 2.0,
        "BEARISH": 1.0
    }

    # Calculate weighted signal score
    scores = []
    signal_values = []

    for signal in analyst_signals:
        sig_str = _signal_label(signal)
        confidence = getattr(signal, 'confidence', 0.5)

        base_score = SIGNAL_SCORE.get(sig_str, 2.0)
        weighted_score = base_score * confidence
        scores.append(weighted_score)
        signal_values.append(SIGNAL_SCORE.get(sig_str, 2.0))

    # 1. Average weighted score
    avg_score = sum(scores) / len(scores) if scores else 0.0

    # 2. Signal consistency (1 - standard deviation, higher is better)
    if len(signal_values) > 1:
        import numpy as np
        std_dev = np.std(signal_values)
        consistency = 1.0 - (std_dev / 2.0)  # Normalize to 0-1
    else:
        consistency = 1.0

    # 3. Bonus for strong bullish consensus
    bullish_count = sum(1 for s in analyst_signals if _signal_label(s) == "BULLISH")
    bullish_ratio = bullish_count / len(analyst_signals)
    bullish_bonus = 0.5 if bullish_ratio >= 0.7 else 0.0  # >70% bullish consensus

    # 4. Penalty for strong bearish consensus (still process, but lower priority)
    bearish_count = sum(1 for s in analyst_signals if _signal_label(s) == "BEARISH")
    bearish_ratio = bearish_count / len(analyst_signals)
    bearish_penalty = -0.3 if bearish_ratio >= 0.7 else 0.0

    # Combine scores
    final_score = avg_score * consistency + bullish_bonus + bearish_penalty

    return round(final_score, 3)


def _calculate_signal_consistency(analyst_signals: List[Any]) -> float:
    """Calculate consistency of analyst signals (0-1, higher = more consistent)."""
    if len(analyst_signals) <= 1:
        return 1.0

    SIGNAL_VALUE = {
        "BULLISH": 1.0,
        "NEUTRAL": 0.5,
        "BEARISH": 0.0
    }

    try:
        import numpy as np
        values = []
        for signal in analyst_signals:
            sig_str = _signal_label(signal)
            values.append(SIGNAL_VALUE.get(sig_str, 0.5))

        # Calculate coefficient of variation (lower = more consistent)
        std_dev = np.std(values)
        mean_val = np.mean(values)
        if mean_val == 0:
            return 1.0  # All BEARISH is consistent

        cv = std_dev / mean_val
        consistency = 1.0 - min(cv, 1.0)  # Convert to 0-1 scale

        return round(consistency, 3)
    except Exception:
        return 0.5  # Default if calculation fails


def _get_smart_priority_order(signals: Dict[str, Any], tickers: List[str]) -> List[str]:
    """
    Determine smart priority order based on collected signals.

    Rules:
    1. Higher priority score first
    2. For equal scores, higher bullish count first
    3. For equal bullish count, higher consistency first
    """
    if not signals:
        return list(tickers)

    # Create list of (ticker, score, details) for sorting
    ticker_data = []
    for ticker, data in signals.items():
        summary = data.get("summary", {})
        ticker_data.append((
            ticker,
            data.get("priority_score", 0.0),
            summary.get("bullish_count", 0),
            summary.get("signal_consistency", 0.0),
            summary.get("avg_confidence", 0.0)
        ))

    # Sort by priority score (descending), then bullish count, then consistency
    sorted_data = sorted(
        ticker_data,
        key=lambda x: (x[1], x[2], x[3], x[4]),
        reverse=True
    )

    # Extract sorted tickers
    sorted_tickers = [item[0] for item in sorted_data]

    # Log the sorting decision
    logger.info(f"Smart priority order: {sorted_tickers}")
    for ticker, score, bullish, consistency, confidence in sorted_data:
        logger.info(f"  {ticker}: score={score:.3f}, bullish={bullish}, consistency={consistency:.3f}, confidence={confidence:.3f}")

    return sorted_tickers
