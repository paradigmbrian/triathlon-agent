"""Date range helpers for APIs with maximum window sizes."""

from datetime import date, timedelta


def date_chunks(start: date, end: date, max_days: int = 90) -> list[tuple[date, date]]:
    """Split [start, end] into inclusive, contiguous chunks with end - start <= max_days."""
    if start > end:
        return []
    chunks: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks
