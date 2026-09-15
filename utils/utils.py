"""Shared helpers used by Module 1 (Chinook demo) and others."""

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


CHINOOK_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chinook.db"


def clear_local_env_vars():
    """Drop company-gateway env vars that would override our service key for this local demo invocation."""
    for _var in (
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        os.environ.pop(_var, None)


def show_graph(graph, xray=False):
    """Display a LangGraph mermaid diagram with ASCII fallback."""
    from IPython.display import Image
    try:
        return Image(graph.get_graph(xray=xray).draw_mermaid_png())
    except Exception as e:
        print(f"Image rendering failed: {e}")
        print("\nFalling back to ASCII:\n")
        print(graph.get_graph(xray=xray).draw_ascii())
        return None


def get_engine_for_chinook_db():
    """Open the bundled Chinook database through a read-only SQLite connection."""
    if not CHINOOK_DB_PATH.is_file():
        raise FileNotFoundError(
            f"Bundled Chinook database not found at {CHINOOK_DB_PATH}"
        )

    def connect_read_only():
        database_uri = f"file:{CHINOOK_DB_PATH.as_posix()}?mode=ro"
        return sqlite3.connect(database_uri, uri=True, check_same_thread=False)

    return create_engine(
        "sqlite://",
        creator=connect_read_only,
        poolclass=StaticPool,
    )
