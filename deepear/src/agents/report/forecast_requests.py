"""Forecast-request parsing/coordination -- extract-report-agent-forecast-and-ticker-coordinator (Phase 4 step 28).

`extract_forecast_requests` and `build_forecast_map` are
`ReportAgent._extract_forecast_requests` and `ReportAgent._build_forecast_map`'s
bodies moved verbatim (docs/refactor_program_plan.md, step 28) out of
`deepear/src/agents/report_agent.py`.

`grep -n "self\\."` restricted to the two original bodies finds four reads
total: `self._clean_ticker(...)` (in both methods),
`self._extract_forecast_requests(...)` and
`self._signal_mentions_ticker(...)` (both in `_build_forecast_map`), and
`self._get_forecast_agent()` (also in `_build_forecast_map`). The first
three all call a function that is itself moving into a leaf module in this
same step -- `clean_ticker`/`signal_mentions_ticker` into the sibling
`deepear/src/agents/report/ticker_utils.py` (a leaf-to-leaf import, not an
import of `report_agent.py`, so no import cycle), and
`extract_forecast_requests` into this same module as `build_forecast_map` --
so, per ground rule 6, those three become direct calls rather than threaded
parameters (there is no `self` left on the callee to thread once it has no
instance state itself), exactly the precedent `citations.py`'s
`_build_bibliography`/`_make_cite_key` move set.

`self._get_forecast_agent()` is the one read this move genuinely threads:
per the program plan's explicit instruction to "inject the lazy
`_get_forecast_agent` callable", `build_forecast_map` takes a required
keyword-only `get_forecast_agent` callable parameter and calls
`get_forecast_agent()` exactly where the original body called
`self._get_forecast_agent()`. `_get_forecast_agent` itself is NOT moved --
it is a genuine per-instance lazy cache (`self._forecast_agent`, `self.db`,
`self.model`) that must keep living on `ReportAgent`, and it is the seam
`tests/report_agent_harness.py` patches around (by swapping the
module-level `ForecastAgent` class, not `_get_forecast_agent` itself).

Monkeypatch audit (ground rule 2): `git grep -n
"_extract_forecast_requests\\|_build_forecast_map\\|_get_forecast_agent"
tests/ deepear/ backtest/ deepfund/ shared/` finds: the method definitions
and their internal call sites in `deepear/src/agents/report_agent.py`
(`generate_report`'s one `self._build_forecast_map` call; `_process_charts`'s
two direct `self._get_forecast_agent()` calls, which belong to step 29's
chart renderer and are untouched here);
`tests/test_report_agent_characterization.py` calls
`harness.agent._extract_forecast_requests(text)` once and
`agent._build_forecast_map(text, signals=...)` twice directly on a real
instance, plus reads `agent._forecast_agent` directly to assert the
lazy-cache identity/count invariant. No literal `monkeypatch.setattr("...")`
string path and no class-attribute patch of either name exists anywhere in
the repo today. `ReportAgent` keeps both as real bound instance methods
(one-line delegators, not bare attribute aliases), and leaves
`_get_forecast_agent` completely untouched, so every internal call site and
any future monkeypatch of any of these names keeps working exactly as
before.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from loguru import logger
import re

from deepear.src.agents.report.ticker_utils import clean_ticker, signal_mentions_ticker
from deepear.src.schema.models import ForecastResult
from deepear.src.utils.json_utils import extract_json


def extract_forecast_requests(text: str, context_window_chars: int = 1200) -> List[Dict[str, Any]]:
    """Extract forecast requests from markdown content.

    Returns list of dicts: {ticker, pred_len, title, context_snippet}
    """
    if not text:
        return []

    pattern = re.compile(r'```json-chart\s*(\{.*?\})\s*```', re.DOTALL)
    requests: List[Dict[str, Any]] = []

    for match in pattern.finditer(text):
        json_str = match.group(1).strip()
        json_str = (
            json_str.replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2018", "'")
            .replace("\u2019", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
        )
        cfg = extract_json(json_str)
        if not cfg:
            continue
        if cfg.get('type') != 'forecast':
            continue

        ticker_raw = str(cfg.get('ticker', '')).strip()
        ticker = clean_ticker(ticker_raw)
        if not (ticker.isdigit() and len(ticker) in (5, 6)):
            continue

        try:
            pred_len = int(cfg.get('pred_len', 5))
        except Exception:
            pred_len = 5
        pred_len = max(1, min(pred_len, 20))

        title = str(cfg.get('title') or f"{ticker_raw} 预测").strip()

        # Prefer writer-provided final attribution over raw surrounding snippet.
        # This supports the workflow: multi-scenario discussion in正文 -> final chosen scenario -> render ONE forecast chart.
        structured_lines: List[str] = []
        selected_scenario = cfg.get('selected_scenario') or cfg.get('scenario') or cfg.get('case')
        selection_reason = cfg.get('selection_reason') or cfg.get('case_reason') or cfg.get('reason')
        scenarios = cfg.get('scenarios')

        if selected_scenario:
            structured_lines.append(f"- 最可能情景: {str(selected_scenario).strip()}")
        if selection_reason:
            structured_lines.append(f"- 归因: {str(selection_reason).strip()}")
        if isinstance(scenarios, list) and scenarios:
            structured_lines.append("- 备选情景:")
            for item in scenarios[:6]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get('name', '')).strip()
                desc = str(item.get('description', '')).strip()
                prob = item.get('probability', None)
                prob_str = ""
                try:
                    if prob is not None:
                        prob_str = f" (p={float(prob):.2f})"
                except Exception:
                    prob_str = ""
                line = "  - " + (name or "（未命名）")
                if desc:
                    line += f": {desc}"
                line += prob_str
                structured_lines.append(line)

        structured_context = ""
        if structured_lines:
            structured_context = "【最终归因/情景选择（作者在 forecast 块中给定）】\n" + "\n".join(structured_lines)

        start = max(0, match.start() - context_window_chars)
        end = min(len(text), match.end() + context_window_chars)
        snippet = text[start:end]
        # remove the code block itself from the snippet to reduce noise
        snippet = snippet.replace(match.group(0), "").strip()
        # remove any other json-chart blocks to avoid polluting forecast context
        snippet = re.sub(r'```json-chart[\s\S]*?```', '', snippet).strip()

        # If structured attribution exists, use it as the primary snippet; keep raw snippet as fallback.
        context_snippet = structured_context or snippet
        if len(context_snippet) > 3500:
            context_snippet = context_snippet[:3500] + "\n\n（上下文过长已截断）"

        requests.append({
            'ticker': ticker,
            'ticker_raw': ticker_raw,
            'pred_len': pred_len,
            'title': title,
            'context_snippet': context_snippet,
        })

    return requests


def build_forecast_map(
    report_text: str,
    signals: Optional[List[Any]] = None,
    *,
    get_forecast_agent: Callable[[], Any],
) -> Dict[tuple, ForecastResult]:
    """Generate forecasts once per unique (ticker, pred_len) to ensure consistency across the report."""
    reqs = extract_forecast_requests(report_text)
    if not reqs:
        return {}

    # Allowlist: only generate forecasts for tickers that are backed by structured signals.
    allowed_tickers: Optional[set[str]] = None
    if signals:
        allowed_tickers = set()
        for s in signals:
            impact = getattr(s, 'impact_tickers', None) if not isinstance(s, dict) else s.get('impact_tickers')
            if not isinstance(impact, list):
                continue
            for item in impact:
                if not isinstance(item, dict):
                    continue
                t = item.get('ticker') or item.get('code') or item.get('symbol')
                tt = clean_ticker(str(t or ""))
                if tt and tt.isdigit() and len(tt) in (5, 6):
                    allowed_tickers.add(tt)
        if not allowed_tickers:
            allowed_tickers = None

    # group by key, merge context
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for r in reqs:
        key = (r['ticker'], int(r['pred_len']))
        g = grouped.get(key)
        if not g:
            grouped[key] = {
                'ticker': r['ticker'],
                'pred_len': int(r['pred_len']),
                'titles': {r['title']},
                'snippets': [r.get('context_snippet', '')],
            }
        else:
            g['titles'].add(r['title'])
            sn = r.get('context_snippet', '')
            if sn and sn not in g['snippets']:
                g['snippets'].append(sn)

    logger.info(f"🔮 Forecast requests: total={len(reqs)}, unique={len(grouped)}")

    forecasts: Dict[tuple, ForecastResult] = {}
    for key, g in grouped.items():
        ticker, pred_len = key

        if allowed_tickers is not None and str(ticker) not in allowed_tickers:
            logger.info(f"ℹ️ Skip forecast for {ticker}: not in validated impact_tickers")
            continue

        related_signals: List[Any] = []
        if signals:
            for s in signals:
                if signal_mentions_ticker(s, str(ticker)):
                    related_signals.append(s)

        # If we have signals context, require at least one related signal for attribution.
        if signals and not related_signals:
            logger.info(f"ℹ️ Skip forecast for {ticker}: no attributable signals")
            continue

        # merge context snippets (cap size)
        merged_snippet = "\n\n---\n\n".join([s for s in g['snippets'] if s])
        if len(merged_snippet) > 3500:
            merged_snippet = merged_snippet[:3500] + "\n\n（上下文过长已截断）"

        extra_context = ""
        if merged_snippet:
            extra_context = (
                "【报告写作上下文（来自章节正文，可能包含主观判断）】\n"
                + merged_snippet
            )

        try:
            fc = get_forecast_agent().generate_forecast(
                str(ticker),
                related_signals,
                pred_len=int(pred_len),
                extra_context=extra_context
            )
            if fc:
                forecasts[key] = fc
        except Exception as e:
            logger.warning(f"⚠️ Forecast generation failed for {ticker} pred_len={pred_len}: {e}")

    return forecasts
