"""Stable QuantArena command-line entry points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Sequence

from quantarena.artifacts import summarize_release_artifacts, validate_release_artifacts
from quantarena.provider_smoke import run_provider_smoke_check
from shared.utils.path_manager import get_project_root, setup_paths


def build_parser() -> argparse.ArgumentParser:
    """Build the QuantArena CLI parser."""
    parser = argparse.ArgumentParser(
        prog="quantarena",
        description="QuantArena engineering and evaluation utilities",
        epilog=(
            "Use `quantarena run --help` to forward to the research experiment runner. "
            "Use `quantarena evaluate --root release_data --json` for offline artifact checks; "
            "`quantarena artifact ...` exposes granular validation; "
            "`quantarena report visualize --root <run-dir>` writes an offline HTML report page."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate a local release artifact bundle without network access",
    )
    evaluate_parser.add_argument(
        "--root",
        type=Path,
        default=Path("release_data"),
        help="Artifact root containing manifest.json and croissant.json",
    )
    evaluate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable evaluation output",
    )
    evaluate_mode_group = evaluate_parser.add_mutually_exclusive_group()
    evaluate_mode_group.add_argument(
        "--strict",
        action="store_true",
        help="Treat validation warnings as failures for CI/release gates",
    )
    evaluate_mode_group.add_argument(
        "--summary",
        action="store_true",
        help="Print a non-validating summary that exits 0 even when warnings are present",
    )

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="Validate this repository checkout layout without network access",
    )
    smoke_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable smoke-check output",
    )

    artifact_parser = subparsers.add_parser(
        "artifact",
        help="Validate local release artifacts without network access",
    )
    artifact_subparsers = artifact_parser.add_subparsers(dest="artifact_command", required=True)
    validate_parser = artifact_subparsers.add_parser(
        "validate",
        help="Validate a release_data-style artifact directory",
    )
    validate_parser.add_argument(
        "--root",
        type=Path,
        default=Path("release_data"),
        help="Artifact root containing manifest.json and croissant.json",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable validation output",
    )
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat validation warnings as failures for CI/release gates",
    )

    summary_parser = artifact_subparsers.add_parser(
        "summary",
        help="Summarize a release_data-style artifact directory",
    )
    summary_parser.add_argument(
        "--root",
        type=Path,
        default=Path("release_data"),
        help="Artifact root containing manifest.json and croissant.json",
    )
    summary_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summary output",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Inspect generated backtest reports",
    )
    report_subparsers = report_parser.add_subparsers(dest="report_command", required=True)
    visualize_parser = report_subparsers.add_parser(
        "visualize",
        help="Generate a standalone HTML visualizer for a backtest report directory",
    )
    visualize_parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Backtest report directory containing metrics.json, equity_curve.csv, and trades.csv",
    )
    visualize_parser.add_argument(
        "--output",
        type=Path,
        help="HTML output path; defaults to <root>/backtest_visualizer.html",
    )
    visualize_parser.add_argument(
        "--title",
        help="Optional page title",
    )
    visualize_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable visualization output",
    )

    provider_parser = subparsers.add_parser(
        "provider",
        help="Run opt-in provider checks for development",
    )
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command", required=True)
    provider_smoke_parser = provider_subparsers.add_parser(
        "smoke",
        help="Run a minimal live daily-candle provider check, skipping cleanly without credentials",
    )
    provider_smoke_parser.add_argument(
        "--market",
        choices=["cn", "us"],
        default="us",
        help="Market to check",
    )
    provider_smoke_parser.add_argument(
        "--provider",
        choices=["alpha_vantage", "fmp", "tushare"],
        help="Provider to check; defaults to configured routing for the selected market",
    )
    provider_smoke_parser.add_argument(
        "--ticker",
        help="Ticker to fetch; defaults to AAPL for US and 600519 for CN",
    )
    provider_smoke_parser.add_argument(
        "--date",
        help="Trading date in YYYY-MM-DD format; defaults to today UTC",
    )
    provider_smoke_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable smoke-check output",
    )
    provider_fixture_parser = provider_subparsers.add_parser(
        "build-news-replay-fixture",
        help="Normalize local news exports into a replay news JSONL fixture",
    )
    provider_fixture_parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Local JSON, JSONL, or CSV news export",
    )
    provider_fixture_parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Replay fixture JSONL output path",
    )
    provider_fixture_parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="Skip invalid rows instead of failing the build",
    )
    provider_fixture_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable fixture build output",
    )

    live_parser = subparsers.add_parser(
        "live",
        help="Inspect a read-only live broker adapter",
    )
    live_parser.add_argument(
        "--provider",
        help="Live read-only provider; defaults to QUANTARENA_LIVE_READONLY_PROVIDER or snapshot",
    )
    live_parser.add_argument(
        "--snapshot",
        type=Path,
        help="Snapshot JSON path for the snapshot live read-only provider",
    )
    live_subparsers = live_parser.add_subparsers(dest="live_command", required=True)
    live_subparsers.add_parser("smoke", help="Run a read-only live broker smoke check")
    live_subparsers.add_parser("account", help="Show live account snapshot")
    live_subparsers.add_parser("positions", help="Show live positions")
    live_orders_parser = live_subparsers.add_parser("orders", help="List live orders")
    live_orders_parser.add_argument("--status", help="Optional order status filter")
    live_orders_parser.add_argument("--symbol", help="Optional symbol filter")
    live_quotes_parser = live_subparsers.add_parser("quotes", help="Show live quotes")
    live_quotes_parser.add_argument("symbols", nargs="*", help="Optional symbols to request")

    paper_parser = subparsers.add_parser(
        "paper",
        help="Operate the local persistent paper portfolio",
    )
    paper_parser.add_argument(
        "--state",
        type=Path,
        help="Paper portfolio state path; defaults to data/paper_portfolio/state.json",
    )
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command", required=True)

    paper_init_parser = paper_subparsers.add_parser("init", help="Initialize paper portfolio state")
    paper_init_parser.add_argument("--cash", type=float, required=True, help="Initial paper cash")
    paper_init_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing paper state file",
    )

    paper_subparsers.add_parser("smoke", help="Run a deterministic paper portfolio smoke check")
    paper_subparsers.add_parser("account", help="Show paper account snapshot")
    paper_subparsers.add_parser("positions", help="Show paper positions")

    paper_orders_parser = paper_subparsers.add_parser("orders", help="List paper orders")
    paper_orders_parser.add_argument("--status", help="Optional order status filter")
    paper_orders_parser.add_argument("--symbol", help="Optional symbol filter")

    paper_quote_parser = paper_subparsers.add_parser("quote", help="Manage paper quotes")
    paper_quote_subparsers = paper_quote_parser.add_subparsers(dest="paper_quote_command", required=True)
    paper_quote_set_parser = paper_quote_subparsers.add_parser("set", help="Set a paper quote")
    paper_quote_set_parser.add_argument("symbol", help="Ticker symbol")
    paper_quote_set_parser.add_argument("price", type=float, help="Last quote price")
    paper_quote_list_parser = paper_quote_subparsers.add_parser("list", help="List paper quotes")
    paper_quote_list_parser.add_argument("symbols", nargs="*", help="Optional symbols to list")

    paper_order_parser = paper_subparsers.add_parser("order", help="Manage paper orders")
    paper_order_subparsers = paper_order_parser.add_subparsers(dest="paper_order_command", required=True)
    paper_order_submit_parser = paper_order_subparsers.add_parser("submit", help="Submit a paper order")
    paper_order_submit_parser.add_argument("--symbol", required=True, help="Ticker symbol")
    paper_order_submit_parser.add_argument(
        "--side",
        required=True,
        choices=["BUY", "SELL", "buy", "sell"],
        help="Order side",
    )
    paper_order_submit_parser.add_argument("--shares", type=int, required=True, help="Order shares")
    paper_order_submit_parser.add_argument("--limit", type=float, required=True, help="Limit price")
    paper_order_submit_parser.add_argument("--justification", default="", help="Order justification")

    paper_order_fill_parser = paper_order_subparsers.add_parser("fill", help="Fill a paper order")
    paper_order_fill_parser.add_argument("order_id", help="Paper order id")
    paper_order_fill_parser.add_argument("--qty", type=int, help="Fill quantity; defaults to remaining")
    paper_order_fill_parser.add_argument("--price", type=float, help="Fill price; defaults to limit")

    paper_order_cancel_parser = paper_order_subparsers.add_parser("cancel", help="Cancel a paper order")
    paper_order_cancel_parser.add_argument("order_id", help="Paper order id")

    paper_reconcile_parser = paper_subparsers.add_parser("reconcile", help="Reconcile expected paper state")
    paper_reconcile_parser.add_argument("--cash", type=float, required=True, help="Expected cash")
    paper_reconcile_parser.add_argument(
        "--position",
        action="append",
        default=[],
        help="Expected position as SYMBOL:SHARES; repeatable",
    )

    return parser


def run_smoke(*, as_json: bool = False) -> int:
    """Run a local no-network smoke check for a source checkout."""
    setup_paths()
    project_root = get_project_root()
    checks = {
        "project_root": str(project_root),
        "backtest_package": _path_exists(project_root / "backtest" / "__init__.py"),
        "deepfund_config": _path_exists(project_root / "deepfund" / "src" / "config"),
        "deepear_config": _path_exists(project_root / "deepear" / "config"),
        "shared_package": _path_exists(project_root / "shared" / "__init__.py"),
    }
    ok = all(value for key, value in checks.items() if key != "project_root")

    if as_json:
        print(json.dumps({"ok": ok, "mode": "source_checkout", "checks": checks}, sort_keys=True))
    else:
        status = "ok" if ok else "failed"
        print(f"QuantArena source-checkout smoke check: {status}")
        for key, value in checks.items():
            print(f"{key}: {value}")

    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the QuantArena CLI."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "run":
        return run_research_runner(effective_argv[1:])

    parser = build_parser()
    args = parser.parse_args(effective_argv)

    if args.command == "smoke":
        return run_smoke(as_json=args.json)

    if args.command == "evaluate":
        if args.summary:
            return run_artifact_summary(root=args.root, as_json=args.json)
        return run_artifact_validate(root=args.root, as_json=args.json, strict=args.strict)

    if args.command == "artifact" and args.artifact_command == "validate":
        return run_artifact_validate(root=args.root, as_json=args.json, strict=args.strict)

    if args.command == "artifact" and args.artifact_command == "summary":
        return run_artifact_summary(root=args.root, as_json=args.json)

    if args.command == "report" and args.report_command == "visualize":
        return run_report_visualize(
            root=args.root,
            output=args.output,
            title=args.title,
            as_json=args.json,
        )

    if args.command == "provider" and args.provider_command == "smoke":
        return run_provider_smoke(
            market=args.market,
            provider=args.provider,
            ticker=args.ticker,
            date=args.date,
            as_json=args.json,
        )

    if args.command == "provider" and args.provider_command == "build-news-replay-fixture":
        return run_news_replay_fixture_builder(
            input_path=args.input,
            output_path=args.output,
            skip_invalid=args.skip_invalid,
            as_json=args.json,
        )

    if args.command == "live":
        return run_live_command(args)

    if args.command == "paper":
        return run_paper_command(args)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def run_research_runner(
    runner_args: Sequence[str],
    *,
    entrypoint: Callable[[], int] | None = None,
) -> int:
    """Forward arguments to the existing research runner without changing its behavior."""
    forwarded_args = _normalize_forwarded_args(runner_args)
    if entrypoint is None:
        from run import main as entrypoint

    original_argv = sys.argv[:]
    try:
        sys.argv = [str(get_project_root() / "run.py"), *forwarded_args]
        return int(entrypoint() or 0)
    finally:
        sys.argv = original_argv


def _normalize_forwarded_args(args: Sequence[str]) -> list[str]:
    """Normalize arguments forwarded through `quantarena run`."""
    forwarded_args = list(args)
    if forwarded_args and forwarded_args[0] == "--":
        return forwarded_args[1:]
    if not forwarded_args:
        return ["--help"]
    return forwarded_args


def _path_exists(path: Path) -> bool:
    return path.exists()


def run_artifact_validate(*, root: Path, as_json: bool = False, strict: bool = False) -> int:
    """Run offline validation for a local release artifact directory."""
    result = validate_release_artifacts(root)
    ok = result.ok and (not strict or not result.warnings)
    if as_json:
        payload = result.to_dict()
        payload["strict"] = strict
        payload["ok"] = ok
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "ok" if ok else "failed"
        print(f"QuantArena artifact validation: {status}")
        print(f"root: {result.root}")
        print(f"strict: {strict}")
        for key, value in result.checks.items():
            print(f"{key}: {value}")
        for error in result.errors:
            print(f"error: {error}", file=sys.stderr)
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)

    return 0 if ok else 1


def run_artifact_summary(*, root: Path, as_json: bool = False) -> int:
    """Summarize a local release artifact directory."""
    result = summarize_release_artifacts(root)
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("QuantArena artifact summary")
        print(f"root: {result.root}")
        print(f"manifest_experiments: {result.stats.get('manifest_experiments', 0)}")
        print(f"manifest_runs: {result.stats.get('manifest_runs', 0)}")
        print(f"documented_only_experiments: {result.stats.get('documented_only_experiments', 0)}")
        print(f"croissant_file_objects: {result.stats.get('croissant_file_objects', 0)}")
        for warning in result.warnings:
            print(f"warning: {warning}")

    return 0


def run_report_visualize(
    *,
    root: Path,
    output: Path | None = None,
    title: str | None = None,
    as_json: bool = False,
) -> int:
    """Generate an offline HTML visualizer for a backtest report directory."""
    from quantarena.backtest_visualizer import write_backtest_visualizer

    result = write_backtest_visualizer(root=root, output=output, title=title)
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if result.ok:
            print("QuantArena backtest visualizer generated")
            print(f"output: {result.output}")
            if result.run_id:
                print(f"run_id: {result.run_id}")
            if result.tickers:
                print(f"tickers: {', '.join(result.tickers)}")
        else:
            print("QuantArena backtest visualizer failed", file=sys.stderr)
            print(f"output: {result.output}", file=sys.stderr)
            for error in result.errors:
                print(f"error: {error['path']}: {error['message']}", file=sys.stderr)

    return 0 if result.ok else 1


def run_provider_smoke(
    *,
    market: str,
    provider: str | None = None,
    ticker: str | None = None,
    date: str | None = None,
    as_json: bool = False,
) -> int:
    """Run an opt-in live provider smoke check."""
    result = run_provider_smoke_check(
        market=market,
        provider=provider,
        ticker=ticker,
        date=date,
    )
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        status = "skipped" if result.skipped else "ok" if result.ok else "failed"
        print(f"QuantArena provider smoke check: {status}")
        print(f"market: {result.market}")
        print(f"provider: {result.provider}")
        print(f"ticker: {result.ticker}")
        print(f"date: {result.date}")
        if result.rows is not None:
            print(f"rows: {result.rows}")
        if result.reason:
            print(f"reason: {result.reason}")

    return 0 if result.ok else 1


def run_news_replay_fixture_builder(
    *,
    input_path: Path,
    output_path: Path,
    skip_invalid: bool = False,
    as_json: bool = False,
) -> int:
    """Build a local replay-news fixture from an archived export."""
    from quantarena.news_replay_fixture_builder import (
        NewsReplayFixtureBuildError,
        build_news_replay_fixture,
    )

    try:
        result = build_news_replay_fixture(
            input_path=input_path,
            output_path=output_path,
            skip_invalid=skip_invalid,
        )
        payload = result.to_dict()
    except NewsReplayFixtureBuildError as exc:
        payload = {
            "ok": False,
            "input_path": str(input_path),
            "output_path": str(output_path),
            "error": str(exc),
        }
        if as_json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("QuantArena news replay fixture build failed", file=sys.stderr)
            print(f"error: {payload['error']}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("QuantArena news replay fixture built")
        print(f"input: {payload['input_path']}")
        print(f"output: {payload['output_path']}")
        print(f"rows: {payload['output_rows']}/{payload['input_rows']}")
        print(f"invalid_rows: {payload['invalid_rows']}")
        print(f"tickers: {', '.join(payload['tickers'])}")

    return 0


def run_paper_command(args: argparse.Namespace) -> int:
    """Run a local paper portfolio command."""
    from trading.paper_portfolio import PaperPortfolioManager

    manager = PaperPortfolioManager(state_path=args.state)
    try:
        result = _dispatch_paper_command(manager, args)
    except Exception as exc:
        result = {
            "ok": False,
            "command": getattr(args, "paper_command", "paper"),
            "result": {},
            "error": str(exc),
        }
    else:
        result = result.to_dict()

    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def run_live_command(args: argparse.Namespace) -> int:
    """Run a read-only live broker command."""
    from trading.live_readonly import LiveReadonlyBrokerManager, LiveReadonlyConfig

    try:
        config = LiveReadonlyConfig.from_env(provider=args.provider, snapshot_path=args.snapshot)
        manager = LiveReadonlyBrokerManager(config=config)
        result = _dispatch_live_command(manager, args).to_dict()
    except Exception as exc:
        result = {
            "ok": False,
            "command": getattr(args, "live_command", "live"),
            "result": {},
            "error": str(exc),
        }

    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


def _dispatch_live_command(manager: object, args: argparse.Namespace):
    if args.live_command == "smoke":
        return manager.smoke()
    if args.live_command == "account":
        return manager.account()
    if args.live_command == "positions":
        return manager.positions()
    if args.live_command == "orders":
        return manager.orders(status=args.status, symbol=args.symbol)
    if args.live_command == "quotes":
        return manager.quotes(symbols=list(args.symbols or []))
    raise ValueError(f"unsupported live command: {args.live_command}")


def _dispatch_paper_command(manager: object, args: argparse.Namespace):
    if args.paper_command == "init":
        return manager.init(initial_cash=args.cash, overwrite=args.overwrite)
    if args.paper_command == "smoke":
        return manager.smoke()
    if args.paper_command == "account":
        return manager.account()
    if args.paper_command == "positions":
        return manager.positions()
    if args.paper_command == "orders":
        return manager.orders(status=args.status, symbol=args.symbol)
    if args.paper_command == "quote" and args.paper_quote_command == "set":
        return manager.set_quote(symbol=args.symbol, price=args.price)
    if args.paper_command == "quote" and args.paper_quote_command == "list":
        return manager.quotes(symbols=list(args.symbols or []))
    if args.paper_command == "order" and args.paper_order_command == "submit":
        return manager.submit_order(
            symbol=args.symbol,
            side=args.side,
            shares=args.shares,
            limit_price=args.limit,
            justification=args.justification,
        )
    if args.paper_command == "order" and args.paper_order_command == "fill":
        return manager.fill_order(order_id=args.order_id, quantity=args.qty, price=args.price)
    if args.paper_command == "order" and args.paper_order_command == "cancel":
        return manager.cancel_order(order_id=args.order_id)
    if args.paper_command == "reconcile":
        return manager.reconcile(
            expected_cash=args.cash,
            expected_positions=_parse_expected_positions(args.position),
        )
    raise ValueError(f"unsupported paper command: {args.paper_command}")


def _parse_expected_positions(items: Sequence[str]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for item in items:
        if ":" not in item:
            raise ValueError(f"invalid position '{item}', expected SYMBOL:SHARES")
        symbol, shares_text = item.split(":", 1)
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError(f"invalid position symbol in '{item}'")
        positions[symbol] = int(shares_text)
    return positions


if __name__ == "__main__":
    sys.exit(main())
