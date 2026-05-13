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
            "`quantarena artifact ...` exposes the granular validation and summary commands."
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

    if args.command == "provider" and args.provider_command == "smoke":
        return run_provider_smoke(
            market=args.market,
            provider=args.provider,
            ticker=args.ticker,
            date=args.date,
            as_json=args.json,
        )

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


if __name__ == "__main__":
    sys.exit(main())
