"""pytest fixtures. Registered from the repository-root conftest via `pytest_plugins`."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from tri_core.config import Settings
from tri_core.db.connection import connect


@pytest.fixture
def db() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Connection to the test database; every test runs in a rolled-back transaction."""
    url = Settings().test_database_url
    try:
        conn = connect(url)
    except psycopg.OperationalError as exc:
        pytest.skip(f"test database unreachable at {url}: {exc}")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
