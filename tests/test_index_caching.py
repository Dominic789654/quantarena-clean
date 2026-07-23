"""
Unit tests for Index Caching in TushareAPI

Tests verify:
1. Cache hit scenarios
2. Cache miss scenarios
3. Data consistency between cache and API
4. TTL expiration for constituents
"""

import os
import sys
import tempfile
import pytest
from datetime import datetime
from unittest.mock import Mock, patch
import pandas as pd

# Add project paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEEPEAR_SRC = os.path.join(PROJECT_ROOT, "deepear", "src")
DEEPFUND_SRC = os.path.join(PROJECT_ROOT, "deepfund", "src")
if DEEPEAR_SRC not in sys.path:
    sys.path.insert(0, DEEPEAR_SRC)
if DEEPFUND_SRC not in sys.path:
    sys.path.insert(0, DEEPFUND_SRC)


class TestDatabaseManagerIndexCaching:
    """Test DatabaseManager index caching methods."""

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        from deepear.src.utils.database_manager import DatabaseManager
        db = DatabaseManager(db_path)
        yield db

        # Cleanup
        db.close()
        os.unlink(db_path)

    def test_save_and_get_index_constituents(self, db):
        """Test saving and retrieving index constituents."""
        index_code = "000300.SH"
        trade_date = "2024-01-15"
        constituents = [
            {'ticker': '600519.SH', 'weight': 0.05, 'name': '贵州茅台'},
            {'ticker': '000858.SZ', 'weight': 0.03, 'name': '五粮液'},
            {'ticker': '601318.SH', 'weight': 0.04, 'name': '中国平安'},
        ]

        # Save
        db.save_index_constituents(index_code, trade_date, constituents)

        # Get
        result = db.get_index_constituents(index_code, trade_date)

        assert result is not None
        assert len(result) == 3
        assert result[0]['ticker'] == '600519.SH'
        assert result[0]['weight'] == 0.05

    def test_constituents_cache_expiration(self, db):
        """Test that constituents cache expires after max_age_days."""
        index_code = "000300.SH"
        trade_date = "2024-01-15"
        constituents = [{'ticker': '600519.SH', 'weight': 0.05, 'name': ''}]

        # Save
        db.save_index_constituents(index_code, trade_date, constituents)

        # Should be available with default TTL
        result = db.get_index_constituents(index_code, trade_date, max_age_days=1)
        assert result is not None

        # Should be expired with 0 days TTL
        result = db.get_index_constituents(index_code, trade_date, max_age_days=0)
        assert result is None

    def test_save_and_get_index_prices(self, db):
        """Test saving and retrieving index prices."""
        index_code = "000300.SH"
        df = pd.DataFrame({
            'date': pd.to_datetime(['2024-01-15', '2024-01-16', '2024-01-17']),
            'open': [3500.0, 3520.0, 3510.0],
            'high': [3550.0, 3570.0, 3560.0],
            'low': [3490.0, 3510.0, 3500.0],
            'close': [3540.0, 3560.0, 3550.0],
            'volume': [1000000, 1100000, 1050000],
            'amount': [3500000000, 3600000000, 3550000000]
        })

        # Save
        db.save_index_prices(index_code, df)

        # Get
        result = db.get_index_prices(index_code, '2024-01-15', '2024-01-17')

        assert not result.empty
        assert len(result) == 3
        assert result.iloc[0]['close'] == 3540.0

    def test_index_prices_cache_miss(self, db):
        """Test that cache miss returns empty DataFrame."""
        result = db.get_index_prices("999999.SH", '2024-01-01', '2024-01-31')
        assert result.empty


class TestTushareAPIIndexCaching:
    """Test TushareAPI index caching integration."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database manager."""
        return Mock()

    @pytest.fixture
    def mock_pro(self):
        """Create a mock Tushare pro API."""
        return Mock()

    @patch('deepfund.src.apis.tushare.api.ts')
    def test_get_index_constituents_cache_hit(self, mock_ts, mock_db):
        """Test that cached constituents are returned without API call."""
        # Setup mock
        mock_ts.pro.client.DataApi = Mock(return_value=Mock())

        # Create cached data
        cached_constituents = [
            {'ticker': '600519.SH', 'weight': 0.05, 'name': ''},
        ]
        mock_db.get_index_constituents = Mock(return_value=cached_constituents)

        # Import after patching
        from deepfund.src.apis.tushare import TushareAPI

        # Create API with db
        with patch.dict(os.environ, {'TUSHARE_API_KEY': 'test_key'}):
            api = TushareAPI(db=mock_db)

        # Call method
        result = api.get_index_constituents('000300.SH', datetime(2024, 1, 15))

        # Verify cache was checked
        mock_db.get_index_constituents.assert_called_once()

        # Verify result
        assert result == cached_constituents

    @patch('tushare.pro.client.DataApi')
    def test_get_index_constituents_cache_miss(self, mock_data_api, mock_db):
        """Test that API is called when cache misses and result is cached."""
        # Setup mock DataApi
        mock_pro = Mock()
        mock_data_api.return_value = mock_pro

        # Create API response
        api_response = pd.DataFrame({
            'con_code': ['600519.SH', '000858.SZ'],
            'weight': [5.0, 3.0],
        })
        mock_pro.index_weight = Mock(return_value=api_response)

        # Cache miss
        mock_db.get_index_constituents = Mock(return_value=None)
        mock_db.save_index_constituents = Mock()

        # Import after patching
        from deepfund.src.apis.tushare import TushareAPI

        # Create API with db
        with patch.dict(os.environ, {'TUSHARE_API_KEY': 'test_key'}):
            api = TushareAPI(db=mock_db)

        # Call method
        result = api.get_index_constituents('000300.SH', datetime(2024, 1, 15))

        # Verify API was called
        mock_pro.index_weight.assert_called_once()

        # Verify result was cached
        mock_db.save_index_constituents.assert_called_once()

        # Verify result
        assert len(result) == 2

    @patch('deepfund.src.apis.tushare.api.ts')
    def test_get_index_daily_cache_hit(self, mock_ts, mock_db):
        """Test that cached index prices are returned without API call."""
        # Setup mock
        mock_ts.pro.client.DataApi = Mock(return_value=Mock())

        # Create cached data
        cached_df = pd.DataFrame({
            'date': pd.to_datetime(['2024-01-15']),
            'open': [3500.0],
            'high': [3550.0],
            'low': [3490.0],
            'close': [3540.0],
            'volume': [1000000],
            'amount': [3500000000]
        }).set_index('date')

        mock_db.get_index_prices = Mock(return_value=cached_df)

        # Import after patching
        from deepfund.src.apis.tushare import TushareAPI

        # Create API with db
        with patch.dict(os.environ, {'TUSHARE_API_KEY': 'test_key'}):
            api = TushareAPI(db=mock_db)

        # Call method
        start = datetime(2024, 1, 15)
        end = datetime(2024, 1, 17)
        result = api.get_index_daily('000300.SH', start, end)

        # Verify cache was checked
        mock_db.get_index_prices.assert_called_once()

        # Verify result
        assert len(result) == 1

    @patch('deepfund.src.apis.tushare.api.ts')
    def test_get_extended_daily_candles_cache_hit(self, mock_ts, mock_db):
        """Test that cached stock prices are returned without API call."""
        # Setup mock
        mock_ts.pro.client.DataApi = Mock(return_value=Mock())

        # Create cached data (enough for lookback)
        dates = pd.date_range(end='2024-01-15', periods=300)
        cached_df = pd.DataFrame({
            'date': dates,
            'open': [100.0] * 300,
            'high': [105.0] * 300,
            'low': [99.0] * 300,
            'close': [103.0] * 300,
            'volume': [1000000] * 300,
            'change_pct': [0.0] * 300
        })

        mock_db.get_stock_prices = Mock(return_value=cached_df)

        # Import after patching
        from deepfund.src.apis.tushare import TushareAPI

        # Create API with db
        with patch.dict(os.environ, {'TUSHARE_API_KEY': 'test_key'}):
            api = TushareAPI(db=mock_db)

        # Call method
        result = api.get_extended_daily_candles('600519.SH', datetime(2024, 1, 15), lookback_days=252)

        # Verify cache was checked
        mock_db.get_stock_prices.assert_called_once()

        # Verify result (should be limited to lookback_days)
        assert len(result) == 252


class TestIntegration:
    """Integration tests with real DatabaseManager."""

    @pytest.fixture
    def real_db(self):
        """Create a real DatabaseManager with temp file."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        from deepear.src.utils.database_manager import DatabaseManager
        db = DatabaseManager(db_path)
        yield db

        # Cleanup
        db.close()
        os.unlink(db_path)

    def test_full_constituents_workflow(self, real_db):
        """Test full workflow: save -> get -> verify."""
        index_code = "000300.SH"
        trade_date = "2024-01-15"

        # Create test data
        constituents = [
            {'ticker': f'{600000+i:06d}.SH', 'weight': 0.01, 'name': f'Stock {i}'}
            for i in range(50)
        ]

        # Save
        real_db.save_index_constituents(index_code, trade_date, constituents)

        # Get
        result = real_db.get_index_constituents(index_code, trade_date)

        # Verify
        assert result is not None
        assert len(result) == 50

        # Verify weights sum to ~1.0
        total_weight = sum(c['weight'] for c in result)
        assert abs(total_weight - 0.5) < 0.01  # 50 * 0.01 = 0.5

    def test_full_prices_workflow(self, real_db):
        """Test full workflow: save -> get -> verify."""
        index_code = "000300.SH"

        # Create test data
        df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=100),
            'open': [3500.0 + i for i in range(100)],
            'high': [3550.0 + i for i in range(100)],
            'low': [3490.0 + i for i in range(100)],
            'close': [3540.0 + i for i in range(100)],
            'volume': [1000000] * 100,
            'amount': [3500000000] * 100
        })

        # Save
        real_db.save_index_prices(index_code, df)

        # Get partial range
        result = real_db.get_index_prices(index_code, '2024-01-10', '2024-01-20')

        # Verify
        assert not result.empty
        assert len(result) == 11  # 10th to 20th inclusive


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
