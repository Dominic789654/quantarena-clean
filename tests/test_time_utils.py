"""
Unit tests for timezone-aware datetime utilities.

Tests the time_utils module including UTC, China timezone, and US Eastern
timezone handling.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from shared.utils.time_utils import (
    now_utc,
    now_cn,
    now_us_eastern,
    format_iso,
    format_timestamp,
    format_date,
    to_utc,
    to_cn_timezone,
    parse_iso,
    is_market_open_cn,
    UTC,
    CHINA_TZ,
    US_EASTERN_TZ,
)


class TestTimezoneConstants:
    """Test timezone constants are correctly defined."""
    
    def test_utc_constant(self):
        """Test UTC timezone constant."""
        assert UTC is timezone.utc
    
    def test_china_tz_constant(self):
        """Test China timezone constant."""
        assert str(CHINA_TZ) == "Asia/Shanghai"
    
    def test_us_eastern_tz_constant(self):
        """Test US Eastern timezone constant."""
        assert str(US_EASTERN_TZ) == "America/New_York"


class TestNowFunctions:
    """Test current time functions."""
    
    def test_now_utc_returns_aware_datetime(self):
        """Test now_utc returns timezone-aware datetime in UTC."""
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.tzinfo is UTC
        assert dt.utcoffset() == timedelta(0)
    
    def test_now_utc_returns_current_time(self):
        """Test now_utc returns current time (within reasonable tolerance)."""
        before = datetime.now(UTC)
        result = now_utc()
        after = datetime.now(UTC)
        
        assert before <= result <= after
    
    def test_now_cn_returns_china_timezone(self):
        """Test now_cn returns timezone-aware datetime in China timezone."""
        dt = now_cn()
        assert dt.tzinfo is not None
        assert str(dt.tzinfo) == "Asia/Shanghai"
    
    def test_now_cn_offset(self):
        """Test China timezone has correct UTC offset (UTC+8)."""
        dt = now_cn()
        # China is UTC+8 (no daylight saving time)
        assert dt.utcoffset() == timedelta(hours=8)
    
    def test_now_us_eastern_returns_aware_datetime(self):
        """Test now_us_eastern returns timezone-aware datetime."""
        dt = now_us_eastern()
        assert dt.tzinfo is not None
        assert str(dt.tzinfo) == "America/New_York"
    
    def test_now_us_eastern_offset(self):
        """Test US Eastern timezone has reasonable UTC offset."""
        dt = now_us_eastern()
        # US Eastern is UTC-5 or UTC-4 (with DST)
        offset = dt.utcoffset()
        assert offset in [timedelta(hours=-5), timedelta(hours=-4)]


class TestFormatIso:
    """Test ISO format function."""
    
    def test_format_iso_default(self):
        """Test format_iso with default parameters."""
        dt = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        result = format_iso(dt)
        assert result == "2026-03-02T04:00:00+00:00"
    
    def test_format_iso_without_timezone(self):
        """Test format_iso without timezone in output."""
        dt = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        result = format_iso(dt, use_timezone=False)
        assert result == "2026-03-02T04:00:00"
        assert "+" not in result
    
    def test_format_iso_uses_current_time_when_none(self):
        """Test format_iso uses current time when dt is None."""
        before = datetime.now(UTC).isoformat()
        result = format_iso()
        after = datetime.now(UTC).isoformat()
        
        # Result should be between before and after
        assert before <= result <= after or result[:16] == before[:16]
    
    def test_format_iso_with_different_timezones(self):
        """Test format_iso handles different timezones."""
        dt_utc = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        dt_cn = datetime(2026, 3, 2, 12, 0, 0, tzinfo=CHINA_TZ)
        
        # Both represent the same moment in time
        assert format_iso(dt_utc) == "2026-03-02T04:00:00+00:00"
        assert "+08:00" in format_iso(dt_cn)


class TestFormatTimestamp:
    """Test timestamp formatting functions."""
    
    def test_format_timestamp_default(self):
        """Test format_timestamp with default format."""
        dt = datetime(2026, 3, 2, 4, 5, 6, tzinfo=UTC)
        result = format_timestamp(dt)
        assert result == "20260302_040506"
    
    def test_format_timestamp_custom_format(self):
        """Test format_timestamp with custom format."""
        dt = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        result = format_timestamp(dt, fmt='%Y-%m-%d')
        assert result == "2026-03-02"
    
    def test_format_date(self):
        """Test format_date convenience function."""
        dt = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        result = format_date(dt)
        assert result == "2026-03-02"


class TestToUtc:
    """Test timezone conversion to UTC."""
    
    def test_to_utc_from_china(self):
        """Test converting China time to UTC."""
        dt_cn = datetime(2026, 3, 2, 12, 0, 0, tzinfo=CHINA_TZ)
        result = to_utc(dt_cn)
        
        assert result.tzinfo is UTC
        # 12:00 China = 04:00 UTC
        assert result.hour == 4
    
    def test_to_utc_from_us_eastern(self):
        """Test converting US Eastern time to UTC."""
        dt_us = datetime(2026, 3, 2, 0, 0, 0, tzinfo=US_EASTERN_TZ)
        result = to_utc(dt_us)
        
        assert result.tzinfo is UTC
    
    def test_to_utc_from_aware_preserves_moment(self):
        """Test to_utc preserves the moment in time."""
        dt_utc = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        dt_cn = datetime(2026, 3, 2, 12, 0, 0, tzinfo=CHINA_TZ)
        
        # Both represent the same moment
        assert to_utc(dt_utc) == to_utc(dt_cn)
    
    def test_to_utc_raises_on_naive(self):
        """Test to_utc raises ValueError for naive datetime."""
        dt_naive = datetime(2026, 3, 2, 4, 0, 0)
        
        with pytest.raises(ValueError) as exc_info:
            to_utc(dt_naive)
        
        assert "naive datetime" in str(exc_info.value)


class TestToCnTimezone:
    """Test timezone conversion to China timezone."""
    
    def test_to_cn_timezone_from_utc(self):
        """Test converting UTC to China timezone."""
        dt_utc = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        result = to_cn_timezone(dt_utc)
        
        assert str(result.tzinfo) == "Asia/Shanghai"
        # 04:00 UTC = 12:00 China
        assert result.hour == 12
    
    def test_to_cn_timezone_from_naive(self):
        """Test to_cn_timezone assumes naive is UTC."""
        dt_naive = datetime(2026, 3, 2, 4, 0, 0)
        result = to_cn_timezone(dt_naive)
        
        assert str(result.tzinfo) == "Asia/Shanghai"


class TestParseIso:
    """Test ISO string parsing."""
    
    def test_parse_iso_with_timezone(self):
        """Test parsing ISO string with timezone."""
        iso_string = "2026-03-02T04:00:00+00:00"
        result = parse_iso(iso_string)
        
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 2
        assert result.hour == 4
        assert result.tzinfo is not None
    
    def test_parse_iso_without_timezone(self):
        """Test parsing ISO string without timezone (assumes UTC)."""
        iso_string = "2026-03-02T04:00:00"
        result = parse_iso(iso_string)
        
        assert result.tzinfo is UTC
    
    def test_parse_iso_roundtrip(self):
        """Test that parse_iso and format_iso are inverse operations."""
        original = datetime(2026, 3, 2, 4, 0, 0, tzinfo=UTC)
        iso_string = format_iso(original)
        result = parse_iso(iso_string)
        
        assert original == result


class TestIsMarketOpenCn:
    """Test Chinese market hours check."""
    
    def test_weekend_market_closed(self):
        """Test market is closed on weekends."""
        # Saturday 10:00 China time
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 7, 10, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is False
        
        # Sunday 10:00 China time
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 8, 10, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is False
    
    def test_morning_session_open(self):
        """Test market is open during morning session."""
        # Monday 10:00 China time (between 9:30 and 11:30)
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 2, 10, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is True
    
    def test_lunch_break_closed(self):
        """Test market is closed during lunch break."""
        # Monday 12:00 China time (between 11:30 and 13:00)
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 2, 12, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is False
    
    def test_afternoon_session_open(self):
        """Test market is open during afternoon session."""
        # Monday 14:00 China time (between 13:00 and 15:00)
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 2, 14, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is True
    
    def test_after_hours_closed(self):
        """Test market is closed after hours."""
        # Monday 16:00 China time (after 15:00)
        with patch('shared.utils.time_utils.now_cn') as mock_now:
            mock_now.return_value = datetime(2026, 3, 2, 16, 0, 0, tzinfo=CHINA_TZ)
            assert is_market_open_cn() is False


class TestIntegration:
    """Integration tests for time utilities."""
    
    def test_timezone_awareness_propagation(self):
        """Test that all now_* functions return aware datetimes."""
        funcs = [now_utc, now_cn, now_us_eastern]
        
        for func in funcs:
            dt = func()
            assert dt.tzinfo is not None, f"{func.__name__} returned naive datetime"
    
    def test_cross_timezone_comparison(self):
        """Test that datetimes from different zones can be compared."""
        utc_time = now_utc()
        cn_time = now_cn()
        us_time = now_us_eastern()
        
        # All should represent similar moments in time
        time_diff_max = timedelta(minutes=1)
        
        # Convert all to UTC for comparison
        utc_from_cn = to_utc(cn_time)
        utc_from_us = to_utc(us_time)
        
        assert abs(utc_time - utc_from_cn) < time_diff_max
        assert abs(utc_time - utc_from_us) < time_diff_max


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
