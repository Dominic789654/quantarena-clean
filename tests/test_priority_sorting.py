"""
Unit tests for smart priority sorting in workflow adapter.
"""

import pytest
import sys
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
DEEPFUND_SRC = PROJECT_ROOT / "deepfund" / "src"
if str(DEEPFUND_SRC) not in sys.path:
    sys.path.insert(0, str(DEEPFUND_SRC))

# Mock signals for testing
class MockAnalystSignal:
    def __init__(self, signal, confidence=0.5, justification="test"):
        self.signal = signal
        self.confidence = confidence
        self.justification = justification

    def __str__(self):
        return str(self.signal)


# Test the real production code (backtest/workflow/scoring.py) rather than
# a hand-copied duplicate — see extract-workflow-scoring-functions.
from backtest.workflow.scoring import (
    _calculate_priority_score as calculate_priority_score,
    _get_smart_priority_order as get_smart_priority_order,
)


class TestPriorityScoreCalculation:
    """Test priority score calculation logic."""

    def test_calculate_priority_score_bullish_consensus(self):
        """Test priority score with bullish consensus."""
        signals = [
            MockAnalystSignal("BULLISH", confidence=0.9),
            MockAnalystSignal("BULLISH", confidence=0.8),
            MockAnalystSignal("BULLISH", confidence=0.7),
        ]

        score = calculate_priority_score(signals)

        # Bullish consensus should get high score
        # BULLISH=3, avg confidence=0.8, so base = 3 * 0.8 = 2.4
        # Consistency=1.0 (all BULLISH)
        # Bullish bonus=0.5 (>70% bullish)
        assert score > 2.8  # 2.4 * 1 + 0.5 = 2.9

    def test_calculate_priority_score_bearish_consensus(self):
        """Test priority score with bearish consensus."""
        signals = [
            MockAnalystSignal("BEARISH", confidence=0.9),
            MockAnalystSignal("BEARISH", confidence=0.8),
            MockAnalystSignal("BEARISH", confidence=0.7),
        ]

        score = calculate_priority_score(signals)

        # Bearish consensus should get low score
        # BEARISH=1, avg confidence=0.8, so base = 1 * 0.8 = 0.8
        # Consistency=1.0 (all BEARISH)
        # Bearish penalty=-0.3 (>70% bearish)
        assert score < 0.6  # 0.8 * 1 - 0.3 = 0.5

    def test_calculate_priority_score_mixed_signals(self):
        """Test priority score with mixed signals."""
        signals = [
            MockAnalystSignal("BULLISH", confidence=0.9),
            MockAnalystSignal("NEUTRAL", confidence=0.7),
            MockAnalystSignal("BEARISH", confidence=0.5),
        ]

        score = calculate_priority_score(signals)

        # Mixed signals should get moderate score
        # Actual calculation: avg_score * consistency (low due to high variance)
        # No bonus/penalty (no consensus)
        assert 0.5 < score < 1.5  # Adjusted based on actual calculation

    def test_calculate_priority_score_empty_signals(self):
        """Test priority score with empty signals."""
        signals = []

        score = calculate_priority_score(signals)

        # Empty signals should return 0.0
        assert score == 0.0

    def test_calculate_priority_score_single_signal(self):
        """Test priority score with single signal."""
        signals = [MockAnalystSignal("BULLISH", confidence=0.9)]

        score = calculate_priority_score(signals)

        # Single BULLISH with high confidence
        # 3 * 0.9 = 2.7, consistency=1.0
        # Single signal = 100% bullish, gets bullish bonus (+0.5)
        assert score > 2.5  # 2.7 + 0.5 bonus = 3.2

    def test_calculate_priority_score_near_consensus(self):
        """Test priority score with near-consensus (66% bullish)."""
        signals = [
            MockAnalystSignal("BULLISH", confidence=0.8),
            MockAnalystSignal("BULLISH", confidence=0.8),
            MockAnalystSignal("NEUTRAL", confidence=0.5),  # 66% bullish, no bonus
        ]

        score = calculate_priority_score(signals)

        # No bullish bonus (< 70%)
        assert score < 2.5  # Should not have +0.5 bonus


class TestSmartPriorityOrder:
    """Test smart priority order determination."""

    def test_get_smart_priority_order_basic(self):
        """Test basic priority ordering."""
        signals = {
            "AAPL": {
                "priority_score": 2.5,
                "summary": {
                    "bullish_count": 2,
                    "signal_consistency": 0.9,
                    "avg_confidence": 0.8
                }
            },
            "MSFT": {
                "priority_score": 1.8,
                "summary": {
                    "bullish_count": 1,
                    "signal_consistency": 0.7,
                    "avg_confidence": 0.6
                }
            },
            "TSLA": {
                "priority_score": 2.2,
                "summary": {
                    "bullish_count": 1,
                    "signal_consistency": 0.8,
                    "avg_confidence": 0.7
                }
            }
        }

        order = get_smart_priority_order(signals, ["AAPL", "MSFT", "TSLA"])

        # Should be sorted by priority score (descending)
        assert order == ["AAPL", "TSLA", "MSFT"]

    def test_get_smart_priority_order_tie_breaker(self):
        """Test priority ordering with tie scores."""
        signals = {
            "AAPL": {
                "priority_score": 2.5,
                "summary": {
                    "bullish_count": 1,  # Less bullish
                    "signal_consistency": 0.9,
                    "avg_confidence": 0.8
                }
            },
            "MSFT": {
                "priority_score": 2.5,
                "summary": {
                    "bullish_count": 2,  # More bullish (tie breaker)
                    "signal_consistency": 0.7,
                    "avg_confidence": 0.6
                }
            }
        }

        order = get_smart_priority_order(signals, ["AAPL", "MSFT"])

        # Same score, MSFT has more bullish count
        assert order == ["MSFT", "AAPL"]

    def test_get_smart_priority_order_empty(self):
        """Test priority ordering with empty signals."""
        signals = {}

        order = get_smart_priority_order(signals, ["AAPL", "MSFT", "TSLA"])

        # Should return original tickers
        assert order == ["AAPL", "MSFT", "TSLA"]

    def test_get_smart_priority_order_partial_signals(self):
        """Test priority ordering with only some tickers having signals."""
        signals = {
            "TSLA": {
                "priority_score": 3.0,
                "summary": {
                    "bullish_count": 3,
                    "signal_consistency": 1.0,
                    "avg_confidence": 0.9
                }
            }
        }

        order = get_smart_priority_order(signals, ["AAPL", "MSFT", "TSLA"])

        # Should only include tickers with signals
        assert len(order) == 1
        assert "TSLA" in order

    def test_get_smart_priority_order_all_equal(self):
        """Test priority ordering when all scores are equal."""
        signals = {
            "AAPL": {
                "priority_score": 2.0,
                "summary": {
                    "bullish_count": 1,
                    "signal_consistency": 0.8,
                    "avg_confidence": 0.7
                }
            },
            "MSFT": {
                "priority_score": 2.0,
                "summary": {
                    "bullish_count": 1,
                    "signal_consistency": 0.8,
                    "avg_confidence": 0.7
                }
            }
        }

        order = get_smart_priority_order(signals, ["AAPL", "MSFT"])

        # All equal, order may vary but should contain both
        assert len(order) == 2
        assert set(order) == {"AAPL", "MSFT"}


class TestMockAnalystSignals:
    """Test mock analyst signals used in testing."""

    def test_mock_signal_str(self):
        """Test string representation of mock signals."""
        signal = MockAnalystSignal("BULLISH", confidence=0.9)
        assert str(signal) == "BULLISH"

    def test_mock_signal_attributes(self):
        """Test attributes of mock signals."""
        signal = MockAnalystSignal("NEUTRAL", confidence=0.7, justification="test reason")
        assert signal.signal == "NEUTRAL"
        assert signal.confidence == 0.7
        assert signal.justification == "test reason"

    def test_mock_signal_default_confidence(self):
        """Test default confidence value."""
        signal = MockAnalystSignal("BEARISH")
        assert signal.confidence == 0.5


if __name__ == "__main__":
    # Run tests if file is executed directly
    pytest.main([__file__, "-v"])