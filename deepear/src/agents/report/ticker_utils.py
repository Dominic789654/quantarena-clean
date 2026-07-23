"""Ticker-string normalization/matching helpers -- extract-report-agent-forecast-and-ticker-coordinator (Phase 4 step 28).

`clean_ticker` and `signal_mentions_ticker` are `ReportAgent._clean_ticker`
and `ReportAgent._signal_mentions_ticker`'s bodies moved verbatim
(docs/refactor_program_plan.md, step 28) out of
`deepear/src/agents/report_agent.py`.

`grep -n "self\\.\\|cls\\."` restricted to the two original bodies finds a
single hit: `_signal_mentions_ticker`'s nested `norm` closure calls
`cls._clean_ticker(s)`. That closure's only reason to exist was to give
`_clean_ticker` a short local name inside the closure body, not to dispatch
through a subclass override, so the one rewrite this move makes is that
closure calling `clean_ticker(s)` directly instead of `cls._clean_ticker(s)`
-- there is no `cls` in a plain module function, and both functions now
live together with no remaining indirection to thread. Everything else in
both bodies moves character-for-character.

Monkeypatch audit (ground rule 2): `git grep -n
"_clean_ticker\\|_signal_mentions_ticker" tests/ deepear/ backtest/
deepfund/ shared/` finds only the two method definitions and their internal
call sites (`self._clean_ticker(...)` inside
`ReportAgent._extract_forecast_requests`/`_build_forecast_map`, and the
nested `norm` closure's former `cls._clean_ticker(...)` call, now rewritten
above) in `deepear/src/agents/report_agent.py`. No test calls either name
directly and no literal `monkeypatch.setattr("...")` string path or
class-attribute patch of either name exists anywhere in the repo today.
`ReportAgent` keeps `_clean_ticker` as a real `@staticmethod` and
`_signal_mentions_ticker` as a real `@classmethod` (each a one-line
delegator, not a bare attribute alias) so a future
`monkeypatch.setattr(ReportAgent, "_clean_ticker", ...)` or
`monkeypatch.setattr(ReportAgent, "_signal_mentions_ticker", ...)`
class-attribute patch would still intercept every internal call site.
"""

from __future__ import annotations

from typing import Any


def clean_ticker(ticker_raw: str) -> str:
    t = (ticker_raw or "").strip()
    if not t:
        return ""
    if "," in t:
        t = t.split(",")[0].strip()
    if "." in t:
        t = t.split(".")[0].strip()
    digits = "".join([c for c in t if c.isdigit()])
    return digits or t


def signal_mentions_ticker(signal: Any, ticker_digits: str) -> bool:
    if not ticker_digits:
        return False

    def norm(s: str) -> str:
        return clean_ticker(s)

    try:
        # Prefer structured impact_tickers if present
        impact = getattr(signal, 'impact_tickers', None) if not isinstance(signal, dict) else signal.get('impact_tickers')
        if isinstance(impact, list):
            for item in impact:
                if not isinstance(item, dict):
                    continue
                t = item.get('ticker') or item.get('code') or item.get('symbol')
                if t and norm(str(t)) == ticker_digits:
                    return True

        # Fallback to text search
        title_text = getattr(signal, 'title', '') if not isinstance(signal, dict) else signal.get('title', '')
        summary_text = getattr(signal, 'summary', '') if not isinstance(signal, dict) else signal.get('summary', '')
        analysis_text = getattr(signal, 'analysis', '') if not isinstance(signal, dict) else signal.get('analysis', '')
        combined = f"{title_text} {summary_text} {analysis_text}"
        return ticker_digits in combined
    except Exception:
        return False
