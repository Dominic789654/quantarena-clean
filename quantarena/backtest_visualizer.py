"""Generate standalone HTML pages for generated backtest report artifacts."""

from __future__ import annotations

import html
import math
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantarena.report_artifacts import RunReportArtifacts, load_run_report_artifacts


@dataclass(frozen=True)
class BacktestVisualizerResult:
    """Result of attempting to generate a backtest visualizer page."""

    ok: bool
    output: Path
    run_id: str | None
    tickers: tuple[str, ...]
    errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": str(self.output),
            "run_id": self.run_id,
            "tickers": list(self.tickers),
            "errors": list(self.errors),
        }


def write_backtest_visualizer(
    root: str | Path,
    *,
    output: str | Path | None = None,
    title: str | None = None,
) -> BacktestVisualizerResult:
    """Write a standalone HTML visualizer for one backtest report directory."""
    report_root = Path(root)
    output_path = Path(output) if output is not None else report_root / "backtest_visualizer.html"
    artifacts = load_run_report_artifacts(report_root)
    tickers = tuple(_extract_tickers(artifacts))
    errors = tuple({"path": str(error.path), "message": error.message} for error in artifacts.errors)
    if errors:
        return BacktestVisualizerResult(
            ok=False,
            output=output_path,
            run_id=artifacts.run_id,
            tickers=tickers,
            errors=errors,
        )

    payload = build_backtest_visualizer_payload(artifacts)
    page = render_backtest_visualizer_html(payload, title=title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return BacktestVisualizerResult(
        ok=True,
        output=output_path,
        run_id=artifacts.run_id,
        tickers=tickers,
    )


def build_backtest_visualizer_payload(artifacts: RunReportArtifacts) -> dict[str, Any]:
    """Build the JSON payload embedded in the generated HTML page."""
    metrics_payload = artifacts.metrics_payload
    summary = metrics_payload.get("summary") if isinstance(metrics_payload.get("summary"), dict) else {}
    final_positions = summary.get("final_positions") if isinstance(summary.get("final_positions"), dict) else {}
    return {
        "schema_version": 1,
        "run": {
            "run_id": artifacts.run_id,
            "root": str(artifacts.root),
            "market": artifacts.market,
            "start_date": metrics_payload.get("start_date"),
            "end_date": metrics_payload.get("end_date"),
            "initial_cash": metrics_payload.get("initial_cash"),
        },
        "tickers": _extract_tickers(artifacts),
        "metrics": artifacts.metrics,
        "summary": summary,
        "equity_curve": artifacts.equity_curve,
        "trades": artifacts.trades,
        "final_positions": _position_rows(final_positions),
    }


def render_backtest_visualizer_html(payload: dict[str, Any], *, title: str | None = None) -> str:
    """Render a standalone HTML document for a visualizer payload."""
    run_id = payload.get("run", {}).get("run_id") or "backtest"
    page_title = title or f"Backtest Visualizer - {run_id}"
    embedded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    safe_title = html.escape(page_title)
    run_subtitle = _run_subtitle(payload)
    ticker_options = _initial_ticker_options(payload.get("tickers", []))
    metric_cards = _initial_metric_cards(payload)
    trades_table = _initial_table(
        [("date", "Date"), ("ticker", "Ticker"), ("action", "Action"), ("shares", "Shares"), ("price", "Price"), ("value", "Value"), ("justification", "Justification")],
        payload.get("trades", []),
    )
    positions_table = _initial_table(
        [("ticker", "Ticker"), ("shares", "Shares"), ("value", "Value"), ("last_price", "Last Price")],
        payload.get("final_positions", []),
    )
    chart_svg = _initial_chart(payload.get("equity_curve", []))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f6f8fb; --panel:#fff; --ink:#172033; --muted:#637083; --line:#dce3ee; --accent:#2563eb; --loss:#dc2626; --gain:#059669; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    header {{ padding: 28px 32px; background: linear-gradient(135deg, #13233f, #1f4f9b); color: white; }}
    header h1 {{ margin: 0 0 8px; font-size: 28px; }}
    header p {{ margin: 0; color: #d7e3ff; }}
    main {{ padding: 24px 32px 40px; display: grid; gap: 20px; }}
    .toolbar, .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 1px 2px rgb(16 24 40 / 6%); }}
    .toolbar {{ padding: 16px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    label {{ color: var(--muted); font-size: 13px; }}
    select {{ min-width: 180px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px; background: white; color: var(--ink); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }}
    .card {{ padding: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 14px; }}
    .card .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    .card .value {{ margin-top: 8px; font-weight: 700; font-size: 24px; }}
    .panel {{ padding: 18px; overflow: hidden; }}
    .panel h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .chart {{ width: 100%; min-height: 280px; border: 1px solid var(--line); border-radius: 12px; background: #fbfdff; }}
    .chart-frame {{ position: relative; }}
    .chart-tooltip {{ position: absolute; z-index: 2; min-width: 220px; padding: 10px 12px; border-radius: 10px; background: rgb(17 24 39 / 94%); color: white; font-size: 12px; line-height: 1.45; box-shadow: 0 10px 24px rgb(16 24 40 / 24%); pointer-events: none; transform: translate(-50%, -110%); }}
    .chart-tooltip[hidden] {{ display: none; }}
    .chart-hover-target {{ cursor: crosshair; pointer-events: all; }}
    .legend {{ display:flex; gap:16px; margin-top:10px; color:var(--muted); font-size:13px; }}
    .legend span::before {{ content:""; display:inline-block; width:10px; height:10px; border-radius:999px; margin-right:6px; }}
    .legend .portfolio::before {{ background: var(--accent); }}
    .legend .benchmark::before {{ background: #f97316; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }}
    .empty {{ color: var(--muted); padding: 18px; text-align: center; }}
    .gain {{ color: var(--gain); }} .loss {{ color: var(--loss); }}
  </style>
</head>
<body>
<header>
  <h1>{safe_title}</h1>
  <p id="run-subtitle">{run_subtitle}</p>
</header>
<main>
  <section class="toolbar" aria-label="Ticker controls">
    <label for="ticker-filter">Ticker view</label>
    <select id="ticker-filter" aria-label="Ticker view filter">{ticker_options}</select>
  </section>
  <section class="cards" id="metric-cards" aria-label="Backtest metrics">{metric_cards}</section>
  <section class="panel">
    <h2>Equity Curve</h2>
    <div class="chart-frame">
      <svg id="equity-chart" class="chart" viewBox="0 0 900 280" role="img" aria-label="Portfolio and benchmark equity curve">{chart_svg}</svg>
      <div id="chart-tooltip" class="chart-tooltip" hidden></div>
    </div>
    <div class="legend"><span class="portfolio">Portfolio</span><span class="benchmark">Benchmark</span></div>
  </section>
  <section class="panel">
    <h2>Trades</h2>
    <div id="trades-table">{trades_table}</div>
  </section>
  <section class="panel">
    <h2>Final Positions</h2>
    <div id="positions-table">{positions_table}</div>
  </section>
</main>
<script id="backtest-data" type="application/json">{embedded_payload}</script>
<script>
const payload = JSON.parse(document.getElementById('backtest-data').textContent);
const tickerFilter = document.getElementById('ticker-filter');
const chartTooltip = document.getElementById('chart-tooltip');
const selectedTicker = () => tickerFilter.value;

function numberValue(value) {{
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}}
function money(value) {{
  const parsed = numberValue(value);
  return parsed === null ? '—' : '$' + parsed.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
}}
function pct(value) {{
  const parsed = numberValue(value);
  return parsed === null ? '—' : parsed.toFixed(2) + '%';
}}
function plain(value) {{
  return value === null || value === undefined || value === '' ? '—' : String(value);
}}
function htmlEscape(value) {{
  return plain(value).replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}
function metricClass(value) {{
  const parsed = numberValue(value);
  return parsed === null ? '' : parsed >= 0 ? 'gain' : 'loss';
}}

function initHeader() {{
  const run = payload.run || {{}};
  document.getElementById('run-subtitle').textContent = `${{plain(run.run_id)}} · ${{plain(run.market)}} · ${{plain(run.start_date)}} to ${{plain(run.end_date)}}`;
}}
function initTickerFilter() {{
  const options = ['ALL', ...(payload.tickers || [])];
  tickerFilter.innerHTML = options.map(ticker => `<option value="${{htmlEscape(ticker)}}">${{ticker === 'ALL' ? 'All tickers' : htmlEscape(ticker)}} </option>`).join('');
  tickerFilter.addEventListener('change', renderFilteredTables);
}}
function renderMetricCards() {{
  const metrics = payload.metrics || {{}};
  const summary = payload.summary || {{}};
  const items = [
    ['Final Value', money(summary.final_value ?? metrics.final_value)],
    ['Total Return', pct(summary.total_return ?? metrics.total_return), metricClass(summary.total_return ?? metrics.total_return)],
    ['Max Drawdown', pct(metrics.max_drawdown)],
    ['Sharpe', plain(metrics.sharpe_ratio)],
    ['Trades', plain(summary.total_trades ?? metrics.total_trades)],
    ['Cash Ratio', pct(numberValue(metrics.avg_cash_ratio) !== null && Math.abs(Number(metrics.avg_cash_ratio)) <= 1 ? Number(metrics.avg_cash_ratio) * 100 : metrics.avg_cash_ratio)],
    ['Exposure', pct(numberValue(metrics.avg_gross_exposure) !== null && Math.abs(Number(metrics.avg_gross_exposure)) <= 1 ? Number(metrics.avg_gross_exposure) * 100 : metrics.avg_gross_exposure)],
  ];
  document.getElementById('metric-cards').innerHTML = items.map(([label, value, cls]) => `<article class="card"><div class="label">${{label}}</div><div class="value ${{cls || ''}}">${{value}}</div></article>`).join('');
}}
function renderChart() {{
  const rows = payload.equity_curve || [];
  const svg = document.getElementById('equity-chart');
  if (!rows.length) {{ svg.innerHTML = '<text x="450" y="140" text-anchor="middle" fill="#637083">No equity data</text>'; return; }}
  const width = 900, height = 280, pad = 28;
  const series = [
    ['total_value', '#2563eb'],
    ['benchmark_value', '#f97316'],
  ].filter(([key]) => rows.some(row => numberValue(row[key]) !== null));
  const values = series.flatMap(([key]) => rows.map(row => numberValue(row[key])).filter(value => value !== null));
  const min = Math.min(...values), max = Math.max(...values);
  const span = max === min ? 1 : max - min;
  const x = index => pad + (rows.length === 1 ? 0 : index * (width - pad * 2) / (rows.length - 1));
  const y = value => height - pad - ((value - min) / span) * (height - pad * 2);
  const polylines = series.map(([key, color]) => {{
    const points = rows.map((row, index) => {{ const value = numberValue(row[key]); return value === null ? null : `${{x(index).toFixed(1)}},${{y(value).toFixed(1)}}`; }}).filter(Boolean).join(' ');
    return `<polyline fill="none" stroke="${{color}}" stroke-width="3" points="${{points}}"/>`;
  }}).join('');
  svg.innerHTML = `<line x1="${{pad}}" y1="${{height-pad}}" x2="${{width-pad}}" y2="${{height-pad}}" stroke="#dce3ee"/>${{polylines}}`;
}}
function initChartHover() {{
  const svg = document.getElementById('equity-chart');
  if (!svg || !chartTooltip) return;
  svg.addEventListener('mousemove', showChartTooltip);
  svg.addEventListener('mouseleave', hideChartTooltip);
}}
function showChartTooltip(event) {{
  const rows = payload.equity_curve || [];
  if (!rows.length || !chartTooltip) return;
  const svg = document.getElementById('equity-chart');
  const rect = svg.getBoundingClientRect();
  const relativeX = Math.min(Math.max(event.clientX - rect.left, 0), rect.width);
  const index = rows.length === 1 ? 0 : Math.round((relativeX / rect.width) * (rows.length - 1));
  const row = rows[Math.min(Math.max(index, 0), rows.length - 1)] || {{}};
  chartTooltip.innerHTML = [
    `<strong>${{htmlEscape(row.date)}}</strong>`,
    `Portfolio: ${{money(row.total_value)}}`,
    `Daily return: ${{pct(row.daily_return)}}`,
    `Benchmark: ${{money(row.benchmark_value)}}`,
    `Benchmark return: ${{pct(row.benchmark_return)}}`,
  ].join('<br>');
  chartTooltip.hidden = false;
  const frameRect = chartTooltip.parentElement.getBoundingClientRect();
  chartTooltip.style.left = `${{event.clientX - frameRect.left}}px`;
  chartTooltip.style.top = `${{event.clientY - frameRect.top}}px`;
}}
function hideChartTooltip() {{
  if (chartTooltip) chartTooltip.hidden = true;
}}
function renderTable(containerId, columns, rows) {{
  const container = document.getElementById(containerId);
  if (!rows.length) {{ container.innerHTML = '<div class="empty">No rows for this ticker view</div>'; return; }}
  const head = columns.map(([key, label]) => `<th>${{htmlEscape(label)}}</th>`).join('');
  const body = rows.map(row => `<tr>${{columns.map(([key]) => `<td>${{htmlEscape(row[key])}}</td>`).join('')}}</tr>`).join('');
  container.innerHTML = `<table><thead><tr>${{head}}</tr></thead><tbody>${{body}}</tbody></table>`;
}}
function renderFilteredTables() {{
  const ticker = selectedTicker();
  const all = ticker === 'ALL';
  const trades = (payload.trades || []).filter(row => all || row.ticker === ticker);
  const positions = (payload.final_positions || []).filter(row => all || row.ticker === ticker);
  renderTable('trades-table', [['date','Date'], ['ticker','Ticker'], ['action','Action'], ['shares','Shares'], ['price','Price'], ['value','Value'], ['justification','Justification']], trades);
  renderTable('positions-table', [['ticker','Ticker'], ['shares','Shares'], ['value','Value'], ['last_price','Last Price']], positions);
}}
initHeader();
initTickerFilter();
renderMetricCards();
renderChart();
initChartHover();
renderFilteredTables();
</script>
</body>
</html>
"""



def _run_subtitle(payload: dict[str, Any]) -> str:
    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    parts = [run.get("run_id"), run.get("market"), f"{run.get('start_date')} to {run.get('end_date')}"]
    return html.escape(" · ".join(str(part) for part in parts if part))


def _initial_ticker_options(tickers: Any) -> str:
    values = ["ALL"]
    if isinstance(tickers, list):
        values.extend(str(ticker) for ticker in tickers if str(ticker).strip())
    return "".join(
        f'<option value="{html.escape(value)}">{html.escape("All tickers" if value == "ALL" else value)}</option>'
        for value in values
    )


def _initial_metric_cards(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    items = [
        ("Final Value", _format_money(summary.get("final_value") or metrics.get("final_value")), ""),
        ("Total Return", _format_percent(summary.get("total_return") or metrics.get("total_return")), _metric_class(summary.get("total_return") or metrics.get("total_return"))),
        ("Max Drawdown", _format_percent(metrics.get("max_drawdown")), ""),
        ("Sharpe", _format_plain(metrics.get("sharpe_ratio")), ""),
        ("Trades", _format_plain(summary.get("total_trades") or metrics.get("total_trades")), ""),
        ("Cash Ratio", _format_ratio(metrics.get("avg_cash_ratio")), ""),
        ("Exposure", _format_ratio(metrics.get("avg_gross_exposure")), ""),
    ]
    return "".join(
        '<article class="card">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div class="value {css_class}">{html.escape(value)}</div>'
        '</article>'
        for label, value, css_class in items
    )



def _initial_chart(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return '<text x="450" y="140" text-anchor="middle" fill="#637083">No equity data</text>'
    series = [
        ("total_value", "#2563eb"),
        ("benchmark_value", "#f97316"),
    ]
    active_series = [
        (key, color)
        for key, color in series
        if any(isinstance(row, dict) and _numeric(row.get(key)) is not None for row in rows)
    ]
    values = [
        value
        for key, _ in active_series
        for row in rows
        if isinstance(row, dict)
        for value in [_numeric(row.get(key))]
        if value is not None
    ]
    if not values:
        return '<text x="450" y="140" text-anchor="middle" fill="#637083">No equity data</text>'

    width = 900
    height = 280
    pad = 28
    low = min(values)
    high = max(values)
    span = 1 if high == low else high - low

    def x_pos(index: int) -> float:
        if len(rows) == 1:
            return float(pad)
        return pad + index * (width - pad * 2) / (len(rows) - 1)

    def y_pos(value: float) -> float:
        return height - pad - ((value - low) / span) * (height - pad * 2)

    polylines = []
    for key, color in active_series:
        points = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            value = _numeric(row.get(key))
            if value is None:
                continue
            points.append(f"{x_pos(index):.1f},{y_pos(value):.1f}")
        if points:
            joined = " ".join(points)
            polylines.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{joined}"/>')

    axis = f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#dce3ee"/>'
    hover_targets = _chart_hover_targets(rows, width, height)
    return axis + "".join(polylines) + hover_targets


def _chart_hover_targets(rows: list[Any], width: int, height: int) -> str:
    if not rows:
        return ""
    band_width = width / len(rows)
    targets = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        x = index * band_width
        title = _chart_title(row)
        targets.append(
            f'<rect class="chart-hover-target" x="{x:.1f}" y="0" width="{band_width:.1f}" height="{height}" fill="transparent" pointer-events="all">'
            f'<title>{html.escape(title)}</title>'
            '</rect>'
        )
    return "".join(targets)


def _chart_title(row: dict[str, Any]) -> str:
    parts = [
        _format_plain(row.get("date")),
        f"Portfolio: {_format_money(row.get('total_value'))}",
        f"Daily return: {_format_percent(row.get('daily_return'))}",
        f"Benchmark: {_format_money(row.get('benchmark_value'))}",
        f"Benchmark return: {_format_percent(row.get('benchmark_return'))}",
    ]
    return "\n".join(parts)

def _initial_table(columns: list[tuple[str, str]], rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return '<div class="empty">No rows for this ticker view</div>'
    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(_format_plain(row.get(key) if isinstance(row, dict) else None))}</td>" for key, _ in columns)
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _format_plain(value: Any) -> str:
    return "—" if value is None or value == "" else str(value)


def _numeric(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _format_money(value: Any) -> str:
    parsed = _numeric(value)
    return "—" if parsed is None else f"${parsed:,.2f}"


def _format_percent(value: Any) -> str:
    parsed = _numeric(value)
    return "—" if parsed is None else f"{parsed:.2f}%"


def _format_ratio(value: Any) -> str:
    parsed = _numeric(value)
    if parsed is None:
        return "—"
    if abs(parsed) <= 1:
        parsed *= 100
    return f"{parsed:.2f}%"


def _metric_class(value: Any) -> str:
    parsed = _numeric(value)
    if parsed is None:
        return ""
    return "gain" if parsed >= 0 else "loss"

def _extract_tickers(artifacts: RunReportArtifacts) -> list[str]:
    seen: dict[str, None] = {}

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            seen.setdefault(value.strip().upper(), None)

    payload = artifacts.metrics_payload
    for ticker in payload.get("tickers", []) if isinstance(payload.get("tickers"), list) else []:
        add(ticker)
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    for ticker in config.get("tickers", []) if isinstance(config.get("tickers"), list) else []:
        add(ticker)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    positions = summary.get("final_positions") if isinstance(summary.get("final_positions"), dict) else {}
    for ticker in positions:
        add(ticker)
    for trade in artifacts.trades:
        add(trade.get("ticker"))
    return list(seen)


def _position_rows(final_positions: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, position in final_positions.items():
        if not isinstance(position, dict):
            continue
        rows.append(
            {
                "ticker": ticker,
                "shares": position.get("shares"),
                "value": position.get("value"),
                "last_price": position.get("last_price"),
            }
        )
    return rows
