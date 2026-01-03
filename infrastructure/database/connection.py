"""
SQLite database connection management.

Provides connection pooling and proper resource cleanup.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "research.db"


class DatabaseConnection:
    """
    SQLite database connection manager.

    Provides:
    - Connection pooling (one per thread)
    - Automatic WAL mode
    - Context manager for transactions
    - Proper resource cleanup
    """

    _local = threading.local()
    _db_path: str = str(DEFAULT_DB_PATH)
    _initialized: bool = False

    @classmethod
    def set_database_path(cls, path: str) -> None:
        """Set the database file path."""
        cls._db_path = path
        cls._initialized = False

    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        """
        Get a connection for the current thread.

        Creates a new connection if one doesn't exist.
        """
        if not hasattr(cls._local, 'connection') or cls._local.connection is None:
            cls._local.connection = cls._create_connection()
        return cls._local.connection

    @classmethod
    def _create_connection(cls) -> sqlite3.Connection:
        """Create a new database connection with proper settings."""
        conn = sqlite3.connect(cls._db_path, check_same_thread=False)

        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Row factory for dict-like access
        conn.row_factory = sqlite3.Row

        logger.debug(f"Created new database connection to {cls._db_path}")
        return conn

    @classmethod
    def close_connection(cls) -> None:
        """Close the connection for the current thread."""
        if hasattr(cls._local, 'connection') and cls._local.connection is not None:
            try:
                cls._local.connection.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            finally:
                cls._local.connection = None

    @classmethod
    @contextmanager
    def transaction(cls):
        """
        Context manager for database transactions.

        Usage:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(...)
                # Auto-commits on success, rolls back on exception
        """
        conn = cls.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @classmethod
    @contextmanager
    def cursor(cls):
        """
        Context manager for getting a cursor with auto-cleanup.

        Usage:
            with DatabaseConnection.cursor() as cursor:
                cursor.execute(...)
                rows = cursor.fetchall()
        """
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()


# Module-level convenience function
def get_connection() -> sqlite3.Connection:
    """Get a database connection for the current thread."""
    return DatabaseConnection.get_connection()
