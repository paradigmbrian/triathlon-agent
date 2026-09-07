"""Postgres connection factory."""

from typing import Any

import psycopg
from psycopg.rows import dict_row


def connect(url: str) -> psycopg.Connection[dict[str, Any]]:
    """Open a connection with dict rows and autocommit off.

    Callers own commit/rollback. Use as a context manager.
    """
    return psycopg.connect(url, row_factory=dict_row, autocommit=False)
