"""
Unit tests for path_manager module.

Tests verify that the unified path manager correctly sets up Python paths.
"""
import pytest
import sys
from pathlib import Path


class TestPathManager:
    """Test path manager functionality."""
    
    def test_path_manager_import(self):
        """Test that path_manager can be imported."""
        from shared.utils.path_manager import setup_paths, get_project_root, PATHS_TO_ADD
        assert setup_paths is not None
        assert get_project_root is not None
        assert len(PATHS_TO_ADD) == 5
    
    def test_setup_paths_adds_required_paths(self):
        """Test that setup_paths adds all required paths."""
        from shared.utils.path_manager import PATHS_TO_ADD
        
        # Verify all required paths are in sys.path
        for required_path in PATHS_TO_ADD:
            assert required_path in sys.path, f"Missing path: {required_path}"
    
    def test_get_project_root_returns_path(self):
        """Test that get_project_root returns a valid Path."""
        from shared.utils.path_manager import get_project_root
        
        root = get_project_root()
        assert isinstance(root, Path)
        assert root.exists()
        assert (root / "deepear").exists()
        assert (root / "deepfund").exists()
    
    def test_get_helper_functions(self):
        """Test helper functions return correct paths."""
        from shared.utils.path_manager import (
            get_project_root,
            get_deepear_src,
            get_deepfund_src,
            get_backtest_dir
        )
        
        root = get_project_root()
        assert get_deepear_src() == root / "deepear" / "src"
        assert get_deepfund_src() == root / "deepfund" / "src"
        assert get_backtest_dir() == root / "backtest"
    
    def test_setup_paths_is_idempotent_via_flag(self):
        """Test that setup_paths uses _initialized flag correctly."""
        from shared.utils.path_manager import _initialized, setup_paths
        
        # After conftest called it, _initialized should be True
        assert _initialized is True
        
        # Calling again should not change anything
        setup_paths()
        
        # _initialized should still be True
        from shared.utils.path_manager import _initialized as still_initialized
        assert still_initialized is True
    
    @pytest.mark.skip(reason="Requires rank_bm25 dependency")
    def test_imports_after_setup(self):
        """Test that key modules can be imported after setup_paths."""
        from shared.utils.path_manager import setup_paths
        setup_paths()
        
        # Test DeepEar imports
        from deepear.src.agents.trend_agent import TrendAgent
        assert TrendAgent is not None
        
        # Test DeepFund imports
        from deepfund.src.graph.workflow import AgentWorkflow
        assert AgentWorkflow is not None
        
        # Test Backtest imports
        from backtest.engine import BacktestEngine
        assert BacktestEngine is not None


class TestDeterministicOrdering:
    """package-path-resolution capability: deepfund/src precedes deepear/src
    regardless of prior sys.path state, so the dual `agents` package always
    resolves to deepfund's analyst registry."""

    @pytest.fixture(autouse=True)
    def restore_sys_path(self):
        from shared.utils import path_manager

        saved = list(sys.path)
        saved_flag = path_manager._initialized
        yield
        sys.path[:] = saved
        path_manager._initialized = saved_flag

    def test_prepolluted_order_is_corrected(self):
        from shared.utils import path_manager
        from shared.utils.path_manager import PATHS_TO_ADD, setup_paths

        deepfund_src = str(path_manager.PROJECT_ROOT / "deepfund" / "src")
        deepear_src = str(path_manager.PROJECT_ROOT / "deepear" / "src")
        for path in PATHS_TO_ADD:
            while path in sys.path:
                sys.path.remove(path)
        sys.path.insert(0, deepfund_src)
        sys.path.insert(0, deepear_src)  # wrong winner on top

        setup_paths(force=True)

        assert sys.path.index(deepfund_src) < sys.path.index(deepear_src)

    def test_idempotent_and_no_duplicates(self):
        from shared.utils.path_manager import PATHS_TO_ADD, setup_paths

        setup_paths(force=True)
        first = list(sys.path)
        setup_paths(force=True)

        assert sys.path == first
        for path in PATHS_TO_ADD:
            assert sys.path.count(path) == 1

    def test_unmanaged_entries_keep_relative_order(self):
        from shared.utils.path_manager import setup_paths

        marker_a, marker_b = "/tmp/zz-unmanaged-a", "/tmp/zz-unmanaged-b"
        sys.path.append(marker_a)
        sys.path.append(marker_b)

        setup_paths(force=True)

        assert sys.path.index(marker_a) < sys.path.index(marker_b)

    def test_bare_agents_import_resolves_to_deepfund(self):
        import agents.registry as registry_mod

        assert "deepfund" in (registry_mod.__file__ or "")

    def test_bare_utils_import_resolves_to_deepear(self):
        """report_agent/search_tools/deepear_client rely on bare `utils.*`
        resolving to deepear/src/utils, never shared/utils."""
        import utils

        assert "deepear" in (utils.__file__ or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
