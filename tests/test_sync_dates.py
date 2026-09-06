from datetime import date

from tri_analyze.sync.dates import date_chunks


def test_single_chunk_when_within_limit():
    assert date_chunks(date(2026, 1, 1), date(2026, 3, 1), 90) == [
        (date(2026, 1, 1), date(2026, 3, 1))
    ]


def test_splits_into_contiguous_chunks():
    chunks = date_chunks(date(2026, 1, 1), date(2026, 12, 31), 90)
    assert chunks[0][0] == date(2026, 1, 1)
    assert chunks[-1][1] == date(2026, 12, 31)
    for (s, e), (ns, _) in zip(chunks, chunks[1:], strict=False):
        assert (e - s).days <= 90
        assert (ns - e).days == 1


def test_same_day():
    assert date_chunks(date(2026, 5, 5), date(2026, 5, 5)) == [(date(2026, 5, 5), date(2026, 5, 5))]


def test_start_after_end_is_empty():
    assert date_chunks(date(2026, 5, 6), date(2026, 5, 5)) == []
