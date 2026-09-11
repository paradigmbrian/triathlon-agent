from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from tri_wellness.testing import NoCommit

TINY_PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R >> endobj\n"
    b"4 0 obj << /Type /Page /Parent 2 0 R >> endobj\n%%EOF\n"
)


@pytest.fixture
def wdb(db):
    """The rolled-back test connection, skipped until 005_wellness.sql is applied."""
    if db.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied to the test database")
    return db


@pytest.fixture
def nocommit(wdb):
    return NoCommit(wdb)


@pytest.fixture
def make_deps(nocommit):
    from tri_wellness.graph.deps import GraphDeps
    from tri_wellness.ranges.registry import load_registry

    registry = load_registry("male")

    def _make(model) -> GraphDeps:
        return GraphDeps(
            model=model, connect=lambda: contextlib.nullcontext(nocommit), registry=registry
        )

    return _make


@pytest.fixture
def tiny_pdf(tmp_path) -> Path:
    p = tmp_path / "panel.pdf"
    p.write_bytes(TINY_PDF)
    return p
