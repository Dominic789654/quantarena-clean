"""
Timezone-aware datetime utilities for the unified agent trading system.

Provides consistent timezone handling across the codebase, using UTC as the
default timezone for all internal operations.
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Default timezone constants
UTC = timezone.utc
CHINA_TZ = ZoneInfo("Asia/Shanghai")  # For Chinese A-share market
US_EASTERN_TZ = ZoneInfo("America/New_York")  # For US stock market


def now_utc() -> datetime:
    """
    Get current time in UTC with timezone info.
    
    Returns:
        Timezone-aware datetime in UTC
        
    Example:
        >>> now_utc()
        datetime.datetime(2026, 3, 2, 4, 0, 0, tzinfo=datetime.timezone.utc)
    """
    return datetime.now(UTC)


def now_cn() -> datetime:
    """
    Get current time in China timezone (Asia/Shanghai).
    
    Used for Chinese A-share market operations.
    
    Returns:
        Timezone-aware datetime in China timezone
        
    Example:
        >>> now_cn()
        datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo('Asia/Shanghai'))
    """
    return datetime.now(CHINA_TZ)


def now_us_eastern() -> datetime:
    """
    Get current time in US Eastern timezone.
    
    Used for US stock market operations.
    
    Returns:
        Timezone-aware datetime in US Eastern timezone
    """
    return datetime.now(US_EASTERN_TZ)


def format_iso(dt: Optional[datetime] = None, use_timezone: bool = True) -> str:
    """
    Format datetime to ISO 8601 string.
    
    Args:
        dt: Datetime to format. If None, uses current UTC time.
        use_timezone: Whether to include timezone offset in output
        
    Returns:
        ISO 8601 formatted string
        
    Example:
        >>> format_iso()
        '2026-03-02T04:00:00+00:00'
        >>> format_iso(use_timezone=False)
        '2026-03-02T04:00:00'
    """
    if dt is None:
        dt = now_utc()
    
    if use_timezone:
        return dt.isoformat()
    else:
        # Remove timezone info for output
        naive = dt.replace(tzinfo=None)
        return naive.isoformat()


def format_timestamp(dt: Optional[datetime] = None, fmt: str = '%Y%m%d_%H%M%S') -> str:
    """
    Format datetime to custom timestamp string.
    
    Args:
        dt: Datetime to format. If None, uses current UTC time.
        fmt: Format string (default: '%Y%m%d_%H%M%S')
        
    Returns:
        Formatted timestamp string
        
    Example:
        >>> format_timestamp()
        '20260302_040000'
        >>> format_timestamp(fmt='%Y-%m-%d')
        '2026-03-02'
    """
    if dt is None:
        dt = now_utc()
    return dt.strftime(fmt)


def format_date(dt: Optional[datetime] = None) -> str:
    """
    Format datetime to date string (YYYY-MM-DD).
    
    Args:
        dt: Datetime to format. If None, uses current UTC time.
        
    Returns:
        Date string in YYYY-MM-DD format
        
    Example:
        >>> format_date()
        '2026-03-02'
    """
    return format_timestamp(dt, '%Y-%m-%d')


def to_utc(dt: datetime) -> datetime:
    """
    Convert any datetime to UTC.
    
    Args:
        dt: Datetime to convert. Can be naive or aware.
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        ValueError: If dt is naive and cannot be assumed as UTC
        
    Example:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2026, 3, 2, 12, 0, 0, tzinfo=ZoneInfo('Asia/Shanghai'))
        >>> to_utc(dt)
        datetime.datetime(2026, 3, 2, 4, 0, 0, tzinfo=datetime.timezone.utc)
    """
    if dt.tzinfo is None:
        # Naive datetime - assume it's UTC or raise error
        raise ValueError(
            "Cannot convert naive datetime to UTC. "
            "Please ensure the datetime has timezone info."
        )
    return dt.astimezone(UTC)


def to_cn_timezone(dt: datetime) -> datetime:
    """
    Convert datetime to China timezone.
    
    Args:
        dt: Datetime to convert. Can be naive or aware.
        
    Returns:
        Timezone-aware datetime in China timezone
    """
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(CHINA_TZ)


def parse_iso(iso_string: str) -> datetime:
    """
    Parse ISO 8601 string to datetime.
    
    Args:
        iso_string: ISO 8601 formatted datetime string
        
    Returns:
        Timezone-aware datetime
        
    Example:
        >>> parse_iso('2026-03-02T04:00:00+00:00')
        datetime.datetime(2026, 3, 2, 4, 0, 0, tzinfo=datetime.timezone.utc)
    """
    # Python 3.7+ supports fromisoformat with timezone
    dt = datetime.fromisoformat(iso_string)
    
    # If no timezone, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    
    return dt


def is_market_open_cn() -> bool:
    """
    Check if Chinese A-share market is currently open.
    
    Market hours: 9:30-11:30, 13:00-15:00 (China time)
    
    Returns:
        True if market is open, False otherwise
    """
    now = now_cn()
    
    # Check weekday (0=Monday, 6=Sunday)
    if now.weekday() >= 5:  # Weekend
        return False
    
    # Check market hours
    time = now.time()
    morning_open = time >= datetime.strptime("09:30", "%H:%M").time()
    morning_close = time <= datetime.strptime("11:30", "%H:%M").time()
    afternoon_open = time >= datetime.strptime("13:00", "%H:%M").time()
    afternoon_close = time <= datetime.strptime("15:00", "%H:%M").time()
    
    return (morning_open and morning_close) or (afternoon_open and afternoon_close)


# Backward compatibility alias
utc_now = now_utc


__all__ = [
    # Timezone constants
    "UTC",
    "CHINA_TZ",
    "US_EASTERN_TZ",
    # Current time functions
    "now_utc",
    "now_cn",
    "now_us_eastern",
    "utc_now",
    # Formatting functions
    "format_iso",
    "format_timestamp",
    "format_date",
    # Conversion functions
    "to_utc",
    "to_cn_timezone",
    "parse_iso",
    # Market functions
    "is_market_open_cn",
]
