"""Checkpointer adapter.

Supports three backends:
- memory: MemorySaver (default, no infrastructure needed)
- sqlite: SqliteSaver with WAL mode for crash-resume demos
- postgres: PostgresSaver for production deployments
"""

from __future__ import annotations

import sqlite3
from typing import Any


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> Any | None:
    """Return a LangGraph checkpointer.

    The SQLite backend uses WAL mode for concurrent read safety and
    creates the database file automatically if it doesn't exist.
    """
    if kind == "none":
        return None

    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()

    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires: pip install langgraph-checkpoint-sqlite"
            ) from exc

        db_path = database_url or "checkpoints.db"
        # Use direct connection with WAL mode for reliability.
        # from_conn_string() returns a context manager in v3, not a checkpointer.
        try:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            return SqliteSaver(conn=conn)
        except TypeError:
            # Fallback for older API versions that use from_conn_string
            return SqliteSaver.from_conn_string(db_path)

    if kind == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "Postgres checkpointer requires: pip install langgraph-checkpoint-postgres"
            ) from exc
        return PostgresSaver.from_conn_string(database_url or "")

    raise ValueError(f"Unknown checkpointer kind: {kind}")
