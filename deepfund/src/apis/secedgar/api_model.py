from typing import Optional
from pydantic import BaseModel


class InstitutionalFiling(BaseModel):
    """Institutional filing metadata from SEC EDGAR submissions (e.g. 13F-HR)."""
    cik: str
    form: str
    filing_date: str
    accession_no: str
    primary_document: Optional[str] = None
    filing_url: Optional[str] = None


class InsiderFiling(BaseModel):
    """Insider (Form 4) filing metadata from SEC EDGAR full-text search."""
    ticker: str
    cik: Optional[str] = None
    filer_names: list[str] = []
    form: str = "4"
    filing_date: Optional[str] = None
    accession_no: Optional[str] = None
    filing_url: Optional[str] = None
