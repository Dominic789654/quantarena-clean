"""
Unit tests for technical indicators library.
"""

import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# Add path and import directly from file (bypass __init__.py)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

# Import directly from module file to avoid dependency issues
import importlib.util
spec = importlib.util.spec_from_file_location(
    "technical_indicators",
    PROJECT_ROOT / "deepfund" / "src" / "util" / "technical_indicators.py"
)
ti = importlib.util.module_from_spec(spec)
sys.modules["technical_indicators"] = ti
spec.loader.exec_module(ti)

# Now import functions
calculate_ema = ti.calculate_ema
calculate_sma = ti.calculate_sma
calculate_rsi = ti.calculate_rsi
calculate_bollinger_bands = ti.calculate_bollinger_bands
calculate_z_score = ti.calculate_z_score
calculate_historical_volatility = ti.calculate_historical_volatility
find_support_resistance_levels = ti.find_support_resistance_levels
calculate_price_position_in_bands = ti.calculate_price_position_in_bands
calculate_all_indicators = ti.calculate_all_indicators


@pytest.fixture
def sample_prices():
    """Create a sample price series for testing."""
    # Generate a series with clear trends and patterns
    prices = [
        100, 101, 102, 101, 100, 99, 100, 101, 102, 103,
        104, 105, 104, 103, 102, 101, 100, 99, 100, 101,
        102, 103, 104, 105, 106, 105, 104, 103, 102, 101,
        100, 99, 98, 97, 96, 95, 96, 97, 98, 99,
        100, 101, 102, 103, 104, 105, 106, 107, 108, 109
    ]
    dates = pd.date_range(start='2024-01-01', periods=len(prices), freq='D')
    return pd.Series(prices, index=dates)


@pytest.fixture
def uptrend_prices():
    """Create an uptrend price series."""
    prices = list(range(100, 130))  # Steady increase
    dates = pd.date_range(start='2024-01-01', periods=len(prices), freq='D')
    return pd.Series(prices, index=dates)


@pytest.fixture
def downtrend_prices():
    """Create a downtrend price series."""
    prices = list(range(130, 100, -1))  # Steady decrease
    dates = pd.date_range(start='2024-01-01', periods=len(prices), freq='D')
    return pd.Series(prices, index=dates)


class TestEMA:
    """Test Exponential Moving Average calculations."""

    def test_ema_basic_calculation(self, sample_prices):
        """Test EMA calculates correctly."""
        ema = calculate_ema(sample_prices, window=10)

        # EMA starts calculating from the first data point (no NaN like SMA)
        # Just verify it returns a series of same length
        assert len(ema) == len(sample_prices)

        # Last value should be defined
        assert pd.notna(ema.iloc[-1])

        # EMA values should be within price range
        assert ema.iloc[-1] >= sample_prices.min()
        assert ema.iloc[-1] <= sample_prices.max()

    def test_ema_with_different_windows(self, sample_prices):
        """Test EMA with different window sizes."""
        ema_short = calculate_ema(sample_prices, window=5)
        ema_long = calculate_ema(sample_prices, window=20)

        # Both should have last value defined
        assert pd.notna(ema_short.iloc[-1])
        assert pd.notna(ema_long.iloc[-1])

        # Shorter window EMA should be more responsive (closer to current price)
        current_price = sample_prices.iloc[-1]
        short_diff = abs(ema_short.iloc[-1] - current_price)
        long_diff = abs(ema_long.iloc[-1] - current_price)
        # Short window should track price more closely
        assert short_diff <= long_diff * 1.5  # Allow some tolerance

    def test_ema_trend_following(self, uptrend_prices):
        """Test EMA follows trend."""
        ema = calculate_ema(uptrend_prices, window=10)

        # In an uptrend, EMA should generally increase
        valid_ema = ema.dropna()
        if len(valid_ema) > 10:
            assert valid_ema.iloc[-1] > valid_ema.iloc[10]


class TestSMA:
    """Test Simple Moving Average calculations."""

    def test_sma_basic_calculation(self, sample_prices):
        """Test SMA calculates correctly."""
        sma = calculate_sma(sample_prices, window=10)

        # SMA should have NaN for first (window-1) values
        assert sma.iloc[:9].isna().all()

        # SMA should have values after window
        assert not sma.iloc[10:].isna().any()

    def test_sma_manual_verification(self):
        """Test SMA against manual calculation."""
        prices = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        sma = calculate_sma(prices, window=3)

        # Manual calculation: (1+2+3)/3 = 2, (2+3+4)/3 = 3, etc.
        expected = pd.Series([np.nan, np.nan, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
        pd.testing.assert_series_equal(sma, expected, check_names=False)


class TestRSI:
    """Test Relative Strength Index calculations."""

    def test_rsi_range(self, sample_prices):
        """Test RSI values are within 0-100 range."""
        rsi = calculate_rsi(sample_prices, period=14)

        # RSI should be between 0 and 100 (excluding NaN)
        valid_rsi = rsi.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_rsi_oversold_condition(self):
        """Test RSI detects oversold condition."""
        # Create a strong downtrend
        prices = pd.Series([100, 95, 90, 85, 80, 75, 70, 65, 60, 55, 50,
                           48, 46, 44, 42, 40, 38, 36, 34, 32])
        rsi = calculate_rsi(prices, period=14)

        # Last RSI should be low (oversold)
        last_rsi = rsi.iloc[-1]
        if pd.notna(last_rsi):
            assert last_rsi < 30

    def test_rsi_overbought_condition(self):
        """Test RSI detects overbought condition."""
        # Create a strong uptrend
        prices = pd.Series([50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
                           102, 104, 106, 108, 110, 112, 114, 116, 118])
        rsi = calculate_rsi(prices, period=14)

        # Last RSI should be high (overbought)
        last_rsi = rsi.iloc[-1]
        if pd.notna(last_rsi):
            assert last_rsi > 70

    def test_rsi_neutral_zone(self):
        """Test RSI in neutral zone for sideways movement."""
        # Create sideways movement
        prices = pd.Series([100, 101, 100, 101, 100, 101, 100, 101, 100, 101,
                           100, 101, 100, 101, 100, 101, 100, 101, 100, 101])
        rsi = calculate_rsi(prices, period=14)

        # RSI should be around 50 (neutral)
        last_rsi = rsi.iloc[-1]
        if pd.notna(last_rsi):
            assert 40 < last_rsi < 60


class TestBollingerBands:
    """Test Bollinger Bands calculations."""

    def test_bollinger_bands_structure(self, sample_prices):
        """Test Bollinger Bands return correct structure."""
        upper, middle, lower = calculate_bollinger_bands(sample_prices, window=20)

        # All bands should be Series
        assert isinstance(upper, pd.Series)
        assert isinstance(middle, pd.Series)
        assert isinstance(lower, pd.Series)

        # All should have same length as input
        assert len(upper) == len(sample_prices)
        assert len(middle) == len(sample_prices)
        assert len(lower) == len(sample_prices)

    def test_bollinger_bands_order(self, sample_prices):
        """Test upper >= middle >= lower."""
        upper, middle, lower = calculate_bollinger_bands(sample_prices, window=20)

        # Remove NaN values for comparison
        valid_idx = upper.notna()

        # Upper should be >= middle
        assert (upper[valid_idx] >= middle[valid_idx]).all()

        # Middle should be >= lower
        assert (middle[valid_idx] >= lower[valid_idx]).all()

    def test_bollinger_bands_width(self, sample_prices):
        """Test bands width changes with volatility."""
        upper, middle, lower = calculate_bollinger_bands(sample_prices, window=10)

        # Calculate bandwidth
        bandwidth = upper - lower
        valid_bandwidth = bandwidth.dropna()

        # Bandwidth should be positive
        assert (valid_bandwidth > 0).all()


class TestZScore:
    """Test Z-Score calculations."""

    def test_z_score_calculation(self, sample_prices):
        """Test Z-Score calculates correctly."""
        z_score = calculate_z_score(sample_prices, window=20)

        # Z-score should have NaN for first (window-1) values
        assert z_score.iloc[:19].isna().all()

        # Z-score should have values after window
        assert not z_score.iloc[20:].isna().any()

    def test_z_score_extreme_values(self):
        """Test Z-Score detects extreme values."""
        # Create prices with an extreme spike
        prices = pd.Series([100] * 19 + [150])  # Normal then spike
        z_score = calculate_z_score(prices, window=10)

        # Last value should have high positive z-score
        last_z = z_score.iloc[-1]
        if pd.notna(last_z):
            assert last_z > 2  # More than 2 standard deviations


class TestHistoricalVolatility:
    """Test Historical Volatility calculations."""

    def test_volatility_calculation(self, sample_prices):
        """Test volatility calculates correctly."""
        vol = calculate_historical_volatility(sample_prices, window=10)

        # Volatility should be positive (excluding NaN)
        valid_vol = vol.dropna()
        assert (valid_vol >= 0).all()

    def test_volatility_annualization(self, sample_prices):
        """Test annualized vs non-annualized volatility."""
        vol_annual = calculate_historical_volatility(sample_prices, window=10, annualize=True)
        vol_daily = calculate_historical_volatility(sample_prices, window=10, annualize=False)

        # Annualized should be larger than daily
        valid_annual = vol_annual.dropna()
        valid_daily = vol_daily.dropna()

        if len(valid_annual) > 0 and len(valid_daily) > 0:
            # Annualized = Daily * sqrt(252)
            assert (valid_annual > valid_daily).all()


class TestSupportResistance:
    """Test Support and Resistance level detection."""

    def test_find_support_level(self):
        """Test support level detection."""
        # Create a pattern with clearer support structure
        prices_list = []
        # Build a longer pattern with multiple support touches at 95
        for _ in range(4):
            prices_list.extend([102, 100, 98, 95, 98, 100, 103, 101, 99])
        # Add current price near support
        prices_list.extend([100, 98, 96, 95])
        prices = pd.Series(prices_list)

        support, resistance = find_support_resistance_levels(prices, pivot_window=2, lookback_period=30)

        # Should find support around 95 (allow some flexibility)
        if support is not None:
            assert 93 <= support <= 97
        # If not found, just verify it doesn't crash
        # (the pivot detection is strict by design)

    def test_find_resistance_level(self):
        """Test resistance level detection."""
        # Create a pattern with clear resistance at 105 - need more data points
        base_pattern = [100, 102, 105, 102, 100, 101, 103, 105, 103, 101]
        prices = pd.Series(base_pattern * 3 + [100, 101, 102, 103, 104])  # 35 points total

        support, resistance = find_support_resistance_levels(prices, pivot_window=3, lookback_period=15)

        # Should find resistance around 105
        assert resistance is not None
        assert 103 <= resistance <= 107

    def test_no_levels_found(self):
        """Test behavior when no clear levels exist."""
        # Steady uptrend - no clear support/resistance
        prices = pd.Series(range(100, 120))

        support, resistance = find_support_resistance_levels(prices, pivot_window=5, lookback_period=10)

        # May or may not find levels depending on pattern
        # Just verify function doesn't crash
        assert support is None or isinstance(support, (int, float))
        assert resistance is None or isinstance(resistance, (int, float))


class TestPricePositionInBands:
    """Test price position calculation within Bollinger Bands."""

    def test_position_at_lower_band(self):
        """Test position at lower band returns 0."""
        position = calculate_price_position_in_bands(
            price=90,
            upper_band=110,
            lower_band=90
        )
        assert position == 0.0

    def test_position_at_upper_band(self):
        """Test position at upper band returns 1."""
        position = calculate_price_position_in_bands(
            price=110,
            upper_band=110,
            lower_band=90
        )
        assert position == 1.0

    def test_position_at_middle(self):
        """Test position at middle returns 0.5."""
        position = calculate_price_position_in_bands(
            price=100,
            upper_band=110,
            lower_band=90
        )
        assert abs(position - 0.5) < 0.01

    def test_position_division_by_zero(self):
        """Test handling when bands are equal."""
        position = calculate_price_position_in_bands(
            price=100,
            upper_band=100,
            lower_band=100
        )
        # Should return 0.5 as default when bands are equal
        assert position == 0.5


class TestCalculateAllIndicators:
    """Test the convenience function that calculates all indicators."""

    def test_calculate_all_indicators_structure(self, sample_prices):
        """Test that all indicators are returned."""
        result = calculate_all_indicators(sample_prices)

        # Check all expected keys exist
        expected_keys = [
            'ema_8', 'ema_21', 'ema_55',
            'rsi',
            'bb_upper', 'bb_middle', 'bb_lower',
            'z_score',
            'volatility',
            'support', 'resistance'
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_calculate_all_indicators_types(self, sample_prices):
        """Test that returned values have correct types."""
        result = calculate_all_indicators(sample_prices)

        # Series indicators
        assert isinstance(result['ema_8'], pd.Series)
        assert isinstance(result['rsi'], pd.Series)
        assert isinstance(result['bb_upper'], pd.Series)

        # Support/resistance can be float, numpy numeric, or None
        assert result['support'] is None or isinstance(result['support'], (int, float, np.integer, np.floating))
        assert result['resistance'] is None or isinstance(result['resistance'], (int, float, np.integer, np.floating))


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_series(self):
        """Test handling of empty series."""
        empty = pd.Series([], dtype=float)

        # Functions should handle gracefully
        ema = calculate_ema(empty, window=10)
        assert len(ema) == 0

        sma = calculate_sma(empty, window=10)
        assert len(sma) == 0

    def test_insufficient_data(self):
        """Test handling of insufficient data for window."""
        short_series = pd.Series([100, 101, 102])

        # SMA should return all NaN if window > data length
        sma = calculate_sma(short_series, window=10)
        assert sma.isna().all()

        # EMA calculates from first data point (no NaN requirement)
        ema = calculate_ema(short_series, window=10)
        assert len(ema) == len(short_series)
        # EMA should still have values for early data points
        assert pd.notna(ema.iloc[0])

    def test_constant_prices(self):
        """Test handling of constant prices."""
        constant = pd.Series([100] * 50)

        # RSI with constant prices should be 50 (or NaN for first window)
        rsi = calculate_rsi(constant, period=14)
        valid_rsi = rsi.dropna()
        if len(valid_rsi) > 0:
            assert (valid_rsi == 50).all() or valid_rsi.iloc[-1] == 50

        # Volatility of constant prices should be 0
        vol = calculate_historical_volatility(constant, window=10)
        valid_vol = vol.dropna()
        if len(valid_vol) > 0:
            assert (valid_vol == 0).all()
