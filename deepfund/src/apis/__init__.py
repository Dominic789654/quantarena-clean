"""API package exports.

Keep optional provider imports lazy/fault-tolerant so one missing dependency
(e.g. yfinance) does not block other providers.
"""


def _missing_provider(name: str, exc: Exception):
    class _MissingProvider:  # pragma: no cover - simple runtime guard
        def __init__(self, *args, **kwargs):
            raise ImportError(f"{name} provider is unavailable: {exc}") from exc

    return _MissingProvider


try:
    from apis.yfinance import YFinanceAPI
except Exception as exc:  # pragma: no cover
    YFinanceAPI = _missing_provider("YFinance", exc)

try:
    from apis.alphavantage import AlphaVantageAPI
except Exception as exc:  # pragma: no cover
    AlphaVantageAPI = _missing_provider("AlphaVantage", exc)

try:
    from apis.fmp import FMPAPI
except Exception as exc:  # pragma: no cover
    FMPAPI = _missing_provider("FMP", exc)

try:
    from apis.tushare import TushareAPI
except Exception as exc:  # pragma: no cover
    TushareAPI = _missing_provider("Tushare", exc)

try:
    from apis.tavily import TavilyNewsAPI
except Exception as exc:  # pragma: no cover
    TavilyNewsAPI = _missing_provider("TavilyNews", exc)

try:
    from apis.akshare import AKShareNewsAPI
except Exception as exc:  # pragma: no cover
    AKShareNewsAPI = _missing_provider("AKShareNews", exc)
