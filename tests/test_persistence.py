"""Tests for persistence module."""

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None,
    reason="langgraph not installed",
)

from langgraph_agent_lab.persistence import build_checkpointer  # noqa: E402


def test_memory_checkpointer():
    cp = build_checkpointer("memory")
    assert cp is not None


def test_none_checkpointer():
    cp = build_checkpointer("none")
    assert cp is None


def test_unknown_raises():
    with pytest.raises(ValueError, match="Unknown checkpointer"):
        build_checkpointer("unknown_backend")


def test_sqlite_checkpointer():
    """Test SQLite checkpointer creation."""
    try:
        cp = build_checkpointer("sqlite", ":memory:")
        assert cp is not None
    except RuntimeError:
        pytest.skip("langgraph-checkpoint-sqlite not installed")
