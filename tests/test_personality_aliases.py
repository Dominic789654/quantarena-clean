"""Tests for personality alias normalization in backtest components."""

import tempfile
from pathlib import Path

import pytest

from backtest.workflow_adapter import BacktestWorkflowAdapter


@pytest.mark.parametrize(
    "alias",
    ["ewi", "equal_weight", "equal_weight_index"],
)
def test_workflow_adapter_normalizes_equal_weight_aliases(alias: str):
    """Equal-weight aliases should be normalized to one canonical personality."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["TEST"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality=alias,
        )
        try:
            assert adapter.personality == "equal_weight_index"
        finally:
            adapter.close()


def test_workflow_adapter_unknown_personality_falls_back_to_balanced():
    """Unknown personality names should use balanced as safe default."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["TEST"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality="unknown_style",
        )
        try:
            assert adapter.personality == "balanced"
        finally:
            adapter.close()


def test_workflow_adapter_preserves_fof_personality():
    """FOF should remain a first-class personality in workflow adapter."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["TEST"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality="fof",
        )
        try:
            assert adapter.personality == "fof"
        finally:
            adapter.close()


@pytest.mark.parametrize(
    ("raw_personality", "normalized"),
    [
        ("fundamental_value", "fundamental_value"),
        ("value", "fundamental_value"),
        ("behavioral_momentum", "behavioral_momentum"),
        ("momentum", "behavioral_momentum"),
        ("macro_tactical", "macro_tactical"),
        ("tactical_allocation", "macro_tactical"),
    ],
)
def test_workflow_adapter_normalizes_new_paradigm_aliases(raw_personality: str, normalized: str):
    """New paradigm aliases should normalize to canonical personality names."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "adapter.db"
        adapter = BacktestWorkflowAdapter(
            tickers=["TEST"],
            initial_cash=100000.0,
            db_path=str(db_path),
            personality=raw_personality,
        )
        try:
            assert adapter.personality == normalized
        finally:
            adapter.close()


@pytest.mark.parametrize(
    "alias",
    ["ewi", "equal_weight", "equal_weight_index"],
)
def test_portfolio_allocator_normalizes_equal_weight_aliases(alias: str):
    """Allocator should map equal-weight aliases to the same personality prompt."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    allocator = PortfolioAllocator(personality=alias)
    assert allocator.personality == "equal_weight_index"
    assert "等权" in allocator.persona_prompt


def test_portfolio_allocator_unknown_personality_falls_back_to_balanced():
    """Allocator should fall back to balanced for unknown personality values."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    allocator = PortfolioAllocator(personality="not_a_personality")
    assert allocator.personality == "balanced"


def test_portfolio_allocator_preserves_fof_personality_prompt():
    """Allocator should expose a dedicated FOF allocator persona."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    allocator = PortfolioAllocator(personality="fof")
    assert allocator.personality == "fof"
    assert "母基金" in allocator.persona_prompt
    assert "15%" in allocator.persona_prompt


def test_portfolio_allocator_import_exposes_alias_registry():
    """Allocator alias registry should be available after module import."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    assert PortfolioAllocator.PERSONALITY_ALIASES["value"] == "fundamental_value"
    assert PortfolioAllocator._normalize_personality("momentum") == "behavioral_momentum"


def test_portfolio_allocator_alias_registry_excludes_unsupported_profiles():
    """Allocator aliases should include only profiles with allocator prompts."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    assert "smart_beta" not in PortfolioAllocator.PERSONALITY_ALIASES
    assert "smart_beta_passive" not in PortfolioAllocator.PERSONALITY_ALIASES
    assert PortfolioAllocator._normalize_personality("smart_beta") == "balanced"


@pytest.mark.parametrize(
    ("raw_personality", "normalized", "expected_text"),
    [
        ("fundamental_value", "fundamental_value", "基本面价值型"),
        ("value", "fundamental_value", "基本面价值型"),
        ("behavioral_momentum", "behavioral_momentum", "行为动量型"),
        ("momentum", "behavioral_momentum", "行为动量型"),
        ("macro_tactical", "macro_tactical", "宏观战术配置型"),
        ("tactical_allocation", "macro_tactical", "宏观战术配置型"),
    ],
)
def test_portfolio_allocator_supports_new_paradigm_aliases(
    raw_personality: str,
    normalized: str,
    expected_text: str,
):
    """Allocator should preserve new paradigm aliases and expose placeholder prompts."""
    pytest.importorskip("agno")
    from backtest.portfolio_allocator import PortfolioAllocator

    allocator = PortfolioAllocator(personality=raw_personality)
    assert allocator.personality == normalized
    assert expected_text in allocator.persona_prompt
