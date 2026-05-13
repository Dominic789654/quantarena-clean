"""
Unit tests for database connection cleanup.

Tests that DatabaseManager, SQLiteDB, and BacktestWorkflowAdapter
properly close their database connections.
"""

import sys
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "deepear" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "deepfund" / "src"))

import pytest


class TestDatabaseManagerConnectionCleanup:
    """Test DatabaseManager connection cleanup."""
    
    def test_connection_closed_on_explicit_close(self):
        """Test that connection is closed when close() is called."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            db = DatabaseManager(str(db_path))
            
            # Connection should be active
            assert db._conn is not None
            
            # Close the connection
            db.close()
            
            # Connection should be None
            assert db._conn is None
            assert db._closed is True
    
    def test_connection_closed_on_context_manager_exit(self):
        """Test that connection is closed when exiting context manager."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            with DatabaseManager(str(db_path)) as db:
                # Connection should be active inside context
                assert db._conn is not None
                conn_id = id(db._conn)
            
            # Connection should be closed after exiting context
            assert db._conn is None
            assert db._closed is True
    
    def test_connection_closed_on_exception_in_context(self):
        """Test that connection is closed even when exception occurs."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            try:
                with DatabaseManager(str(db_path)) as db:
                    assert db._conn is not None
                    raise ValueError("Test exception")
            except ValueError:
                pass  # Expected
            
            # Connection should still be closed
            assert db._conn is None
    
    def test_access_closed_connection_raises_error(self):
        """Test that accessing closed connection raises RuntimeError."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            db = DatabaseManager(str(db_path))
            db.close()
            
            with pytest.raises(RuntimeError) as exc_info:
                _ = db.conn
            
            assert "closed" in str(exc_info.value).lower()
    
    def test_close_idempotent(self):
        """Test that close() can be called multiple times without error."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            db = DatabaseManager(str(db_path))
            
            # Should not raise
            db.close()
            db.close()
            db.close()
            
            assert db._conn is None


class TestSQLiteDBConnectionCleanup:
    """Test SQLiteDB connection cleanup."""
    
    def test_close_method_exists(self):
        """Test that SQLiteDB has close() method."""
        # Skip if deepfund dependencies not available
        try:
            from deepfund.src.database.sqlite_helper import SQLiteDB
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        
        db = SQLiteDB()
        assert hasattr(db, 'close')
        
        # Should not raise
        db.close()
    
    def test_context_manager_support(self):
        """Test that SQLiteDB supports context manager."""
        try:
            from deepfund.src.database.sqlite_helper import SQLiteDB
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        
        with SQLiteDB() as db:
            assert db is not None
            assert hasattr(db, '_get_connection')
        
        # Should exit without error
    
    def test_connection_per_operation_closed(self):
        """Test that connections are closed after each operation."""
        try:
            from deepfund.src.database.sqlite_helper import SQLiteDB
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            # Create a test database
            conn = sqlite3.connect(str(db_path))
            conn.execute('CREATE TABLE test (id INTEGER PRIMARY KEY)')
            conn.close()
            
            db = SQLiteDB()
            db.set_db_path(str(db_path))
            
            # Each operation should open and close its own connection
            # We can't directly test this, but we can verify operations work
            result = db.get_config("nonexistent")
            assert result is None
            
            # Database file should not be locked
            # Try to open another connection
            conn2 = sqlite3.connect(str(db_path))
            conn2.execute('SELECT 1')
            conn2.close()

    def test_connection_sets_busy_timeout_and_wal_mode(self):
        """Test SQLite connections are configured for lock contention resilience."""
        try:
            from deepfund.src.database.sqlite_helper import SQLiteDB
        except ImportError as e:
            pytest.skip(f"DeepFund dependencies not available: {e}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"

            conn = sqlite3.connect(str(db_path))
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            conn.close()

            db = SQLiteDB()
            db.set_db_path(str(db_path))
            conn = db._get_connection()
            try:
                busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

                assert busy_timeout >= 30000
                assert str(journal_mode).lower() == "wal"
                # 1 means NORMAL in SQLite
                assert int(synchronous) in {1, 2}
            finally:
                conn.close()


class TestBacktestWorkflowAdapterCleanup:
    """Test BacktestWorkflowAdapter cleanup."""
    
    def test_close_method_exists(self):
        """Test that BacktestWorkflowAdapter has close() method."""
        from backtest.workflow_adapter import BacktestWorkflowAdapter
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            adapter = BacktestWorkflowAdapter(
                tickers=["TEST"],
                initial_cash=100000,
                db_path=str(db_path)
            )
            
            assert hasattr(adapter, 'close')
            
            # Should not raise
            adapter.close()
    
    def test_context_manager_support(self):
        """Test that BacktestWorkflowAdapter supports context manager."""
        from backtest.workflow_adapter import BacktestWorkflowAdapter
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            with BacktestWorkflowAdapter(
                tickers=["TEST"],
                initial_cash=100000,
                db_path=str(db_path)
            ) as adapter:
                assert adapter is not None
                assert hasattr(adapter, 'run_single_day')
            
            # Should exit without error
    
    def test_no_persistent_connection_leak(self):
        """Test that adapter doesn't leak persistent connections."""
        from backtest.workflow_adapter import BacktestWorkflowAdapter
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            # Create adapter
            adapter = BacktestWorkflowAdapter(
                tickers=["TEST"],
                initial_cash=100000,
                db_path=str(db_path)
            )
            
            # Close it
            adapter.close()
            
            # Database should not be locked - we can open a new connection
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            conn.close()


class TestDatabaseFileLocking:
    """Test that database files are properly released."""
    
    def test_database_manager_releases_file(self):
        """Test that DatabaseManager releases the database file on close."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            
            # Create and close database
            db = DatabaseManager(str(db_path))
            db.close()
            
            # Should be able to delete the file
            assert db_path.exists()
            db_path.unlink()  # This would fail if file is locked
            assert not db_path.exists()
    
    def test_multiple_instances_no_conflict(self):
        """Test that multiple instances can use different databases."""
        from deepear.src.utils.database_manager import DatabaseManager
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path1 = Path(tmp_dir) / "test1.db"
            db_path2 = Path(tmp_dir) / "test2.db"
            
            db1 = DatabaseManager(str(db_path1))
            db2 = DatabaseManager(str(db_path2))
            
            # Both should work independently
            assert db1._conn is not None
            assert db2._conn is not None
            
            # Close both
            db1.close()
            db2.close()
            
            assert db1._conn is None
            assert db2._conn is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
