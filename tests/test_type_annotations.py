"""
Tests for type annotations.

Verifies that key functions have proper type annotations.
"""

import sys
from pathlib import Path
from typing import get_type_hints

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pytest


class TestRunPyTypeAnnotations:
    """Test type annotations in run.py"""
    
    def test_fix_tushare_token_file_has_return_annotation(self):
        """Test _fix_tushare_token_file has None return type."""
        from run import _fix_tushare_token_file
        hints = get_type_hints(_fix_tushare_token_file)
        assert 'return' in hints
        assert hints['return'] is type(None)
    
    def test_print_banner_has_return_annotation(self):
        """Test print_banner has None return type."""
        from run import print_banner
        hints = get_type_hints(print_banner)
        assert 'return' in hints
        assert hints['return'] is type(None)
    
    def test_check_env_file_has_return_annotation(self):
        """Test check_env_file has bool return type."""
        from run import check_env_file
        hints = get_type_hints(check_env_file)
        assert 'return' in hints
        assert hints['return'] is bool
    
    def test_run_deepear_has_annotations(self):
        """Test run_deepear has proper type annotations."""
        from run import run_deepear
        hints = get_type_hints(run_deepear)
        assert 'return' in hints
        assert hints['return'] is int
        assert 'args' in hints
    
    def test_run_deepfund_has_annotations(self):
        """Test run_deepfund has proper type annotations."""
        from run import run_deepfund
        hints = get_type_hints(run_deepfund)
        assert 'return' in hints
        assert hints['return'] is int
    
    def test_run_backtest_mode_has_annotations(self):
        """Test run_backtest_mode has proper type annotations."""
        from run import run_backtest_mode
        hints = get_type_hints(run_backtest_mode)
        assert 'return' in hints
        assert hints['return'] is int
    
    def test_run_multi_personality_mode_has_annotations(self):
        """Test run_multi_personality_mode has proper type annotations."""
        from run import run_multi_personality_mode
        hints = get_type_hints(run_multi_personality_mode)
        assert 'return' in hints
        assert hints['return'] is int
    
    def test_main_has_return_annotation(self):
        """Test main has int return type."""
        from run import main
        hints = get_type_hints(main)
        assert 'return' in hints
        assert hints['return'] is int


class TestWorkflowTypeAnnotations:
    """Test type annotations in workflow.py"""
    
    def test_agent_workflow_init_has_annotations(self):
        """Test AgentWorkflow.__init__ has type annotations."""
        try:
            from deepfund.src.graph.workflow import AgentWorkflow
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        hints = get_type_hints(AgentWorkflow.__init__)
        assert 'config' in hints
        assert 'config_id' in hints
        assert 'market' in hints
    
    def test_update_portfolio_ticker_has_annotations(self):
        """Test update_portfolio_ticker has return annotation."""
        try:
            from deepfund.src.graph.workflow import AgentWorkflow
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        hints = get_type_hints(AgentWorkflow.update_portfolio_ticker)
        assert 'return' in hints


class TestBaseAnalystTypeAnnotations:
    """Test type annotations in base analyst."""
    
    def test_base_analyst_init_has_annotations(self):
        """Test BaseAnalyst.__init__ has type annotations."""
        try:
            from deepfund.src.agents.analysts.base import BaseAnalyst
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        hints = get_type_hints(BaseAnalyst.__init__)
        assert 'agent_key' in hints
        assert 'prompt_template' in hints
        assert 'thresholds' in hints
    
    def test_analyze_has_annotations(self):
        """Test analyze has type annotations."""
        try:
            from deepfund.src.agents.analysts.base import BaseAnalyst
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        hints = get_type_hints(BaseAnalyst.analyze)
        assert 'return' in hints


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
