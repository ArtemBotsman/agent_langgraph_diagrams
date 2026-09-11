"""Local persistence helpers for reproducible root-orchestrator runs."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Restrict checkpoint deserialization as recommended by the LangGraph SQLite
# package. This must be set before importing the saver implementation.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402


@contextmanager
def open_sqlite_checkpointer(path: Path) -> Iterator[Any]:
    """Yield a lightweight durable checkpointer suitable for local experiments."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        yield SqliteSaver(connection)
    finally:
        connection.close()


def thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    """Return the required LangGraph invocation config for persisted state."""

    if not thread_id.strip():
        raise ValueError("thread_id must be non-empty")
    return {"configurable": {"thread_id": thread_id}}
