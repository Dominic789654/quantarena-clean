"""Dry-run warmup planning for fixed backtest cache inputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from quantarena.cache_health import (
    DEFAULT_BENCHMARK_CACHE_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_NEWS_REPLAY_PATH,
    DEFAULT_SHARED_ANALYST_CACHE_DIR,
    DEFAULT_SHARED_PHASE1_CACHE_DIR,
    CacheHealthFinding,
    CacheHealthReport,
    FixedBacktestCacheHealthConfig,
    run_fixed_backtest_cache_health,
)


@dataclass(frozen=True)
class FixedBacktestWarmupAction:
    """One unresolved fixed cache warmup action."""

    layer: str
    reason: str
    path: str | None
    required: bool
    recommended_command: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "reason": self.reason,
            "path": self.path,
            "required": self.required,
            "recommended_command": self.recommended_command,
            "details": self.details,
        }


@dataclass(frozen=True)
class FixedBacktestWarmupPlan:
    """A fixed backtest cache warmup plan."""

    ok: bool
    profile: str
    dry_run: bool
    health: CacheHealthReport
    actions: tuple[FixedBacktestWarmupAction, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "profile": self.profile,
            "dry_run": self.dry_run,
            "health": self.health.to_dict(),
            "actions": [action.to_dict() for action in self.actions],
            "required_action_count": sum(1 for action in self.actions if action.required),
        }


def build_parser() -> argparse.ArgumentParser:
    """Build the fixed cache warmup CLI parser."""
    parser = argparse.ArgumentParser(
        prog="run_fixed_backtest_cache_warmup.py",
        description="Plan fixed backtest cache preparation without writing cache files.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--benchmark-cache-dir", type=Path, default=DEFAULT_BENCHMARK_CACHE_DIR)
    parser.add_argument("--news-replay-fixture", type=Path, default=DEFAULT_NEWS_REPLAY_PATH)
    parser.add_argument("--shared-phase1-cache-dir", type=Path, default=DEFAULT_SHARED_PHASE1_CACHE_DIR)
    parser.add_argument("--shared-analyst-cache-dir", type=Path, default=DEFAULT_SHARED_ANALYST_CACHE_DIR)
    parser.add_argument("--json", action="store_true", help="Print machine-readable plan output")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when required actions remain")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run fixed cache warmup planning from CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)
    plan = build_fixed_backtest_cache_warmup_plan(
        FixedBacktestCacheHealthConfig(
            db_path=args.db_path,
            benchmark_cache_dir=args.benchmark_cache_dir,
            news_replay_path=args.news_replay_fixture,
            shared_phase1_cache_dir=args.shared_phase1_cache_dir,
            shared_analyst_cache_dir=args.shared_analyst_cache_dir,
        )
    )
    if args.json:
        print(json.dumps(plan.to_dict(), sort_keys=True))
    else:
        _print_human_plan(plan)
    return 0 if plan.ok or not args.strict else 1


def build_fixed_backtest_cache_warmup_plan(
    config: FixedBacktestCacheHealthConfig | None = None,
) -> FixedBacktestWarmupPlan:
    """Build a dry-run warmup plan from fixed-backtest cache health."""
    health = run_fixed_backtest_cache_health(config)
    actions = tuple(_action_from_finding(finding, health) for finding in health.findings)
    required_actions = [action for action in actions if action.required]
    return FixedBacktestWarmupPlan(
        ok=not required_actions,
        profile="fixed-backtest",
        dry_run=True,
        health=health,
        actions=actions,
    )


def _action_from_finding(
    finding: CacheHealthFinding,
    health: CacheHealthReport,
) -> FixedBacktestWarmupAction:
    layer = next((layer for layer in health.layers if layer.name == finding.layer), None)
    required = bool(layer.required) if layer else True
    details = dict(layer.details) if layer else {}
    return FixedBacktestWarmupAction(
        layer=finding.layer,
        reason=finding.reason,
        path=finding.path,
        required=required,
        recommended_command=_recommended_command(finding.layer, finding.path),
        details=details,
    )


def _recommended_command(layer: str, path: str | None) -> str:
    if layer == "stock_price_db":
        return "Run the fixed backtest data prefetch path or provider sync for AAPL,MSFT,NVDA, then rerun cache health."
    if layer == "benchmark_price_cache":
        target = f" at {path}" if path else ""
        return f"Build the ^GSPC benchmark close JSONL cache{target}, then rerun cache health."
    if layer == "news_replay_fixture":
        target = f" --output {path}" if path else ""
        return f"Run quantarena provider build-news-replay-fixture with an archived news export{target}."
    return "Resolve the cache health finding, then rerun fixed cache warmup."


def _print_human_plan(plan: FixedBacktestWarmupPlan) -> None:
    print("Fixed backtest cache warmup")
    print(f"profile: {plan.profile}")
    print(f"dry_run: {plan.dry_run}")
    print(f"ok: {plan.ok}")
    if not plan.actions:
        print("actions: none")
        return
    for action in plan.actions:
        required = "required" if action.required else "optional"
        print(f"- {action.layer}: {action.reason} ({required})")
        if action.path:
            print(f"  path: {action.path}")
        print(f"  next: {action.recommended_command}")


if __name__ == "__main__":
    raise SystemExit(main())
