"""
SEC EDGAR 内幕交易/机构持仓底层工具

复用 DeepFund 的 SECEdgarAPI provider（setup_paths 已将 deepfund/src 加入
sys.path），为 DeepEar 情报流提供 Form 4 高管交易与 13F 机构持仓查询。
"""

from typing import Dict, List, Optional

from loguru import logger


class InsiderTools:
    """SEC EDGAR insider/institutional filing tools for DeepEar."""

    def __init__(self):
        self._api = None
        self._init_error: Optional[str] = None

    def _get_api(self):
        """Lazily build the SEC EDGAR client so a missing User-Agent only
        fails the insider tools, not the whole agent toolchain."""
        if self._api is not None:
            return self._api
        if self._init_error is not None:
            raise RuntimeError(self._init_error)
        try:
            from apis.secedgar import SECEdgarAPI  # provided by deepfund/src on sys.path
            self._api = SECEdgarAPI()
        except Exception as exc:
            self._init_error = f"SEC EDGAR unavailable: {exc}"
            logger.warning(self._init_error)
            raise RuntimeError(self._init_error) from exc
        return self._api

    def get_recent_insider_filings(self, ticker: str, days_back: int = 30,
                                   limit: int = 20) -> List[Dict]:
        """获取某美股 ticker 近 N 天的 Form 4 高管交易 filing 列表."""
        filings = self._get_api().get_insider_filings(
            ticker, days_back=days_back, limit=limit
        )
        return [f.model_dump() for f in filings]

    def get_institution_13f(self, institution: str, limit: int = 5) -> List[Dict]:
        """获取某机构（别名或 CIK）最近的 13F-HR 持仓报告 filing 列表."""
        filings = self._get_api().get_institutional_filings(institution, limit=limit)
        return [f.model_dump() for f in filings]
