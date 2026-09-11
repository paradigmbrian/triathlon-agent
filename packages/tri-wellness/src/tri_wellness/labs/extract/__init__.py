"""sniff(file) -> source kind, plus the file-level helpers the graph and CLI share."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tri_wellness.labs.models import IngestKind

_PAGE = re.compile(rb"/Type\s*/Page[^s]")
_EXPORT_SUFFIXES = frozenset({".csv", ".tsv", ".json"})


def sniff(path: Path, kind: IngestKind | None = None) -> IngestKind:
    if kind is not None:
        return kind
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in _EXPORT_SUFFIXES:
        return "export"
    raise ValueError(f"cannot tell the source kind from '{path.name}'; pass --kind pdf|export")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_pdf_pages(data: bytes) -> int:
    """Page objects in the file. A regex over the bytes; good enough for a tag and a log line."""
    return len(_PAGE.findall(data))
