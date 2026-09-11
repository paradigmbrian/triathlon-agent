import pytest


@pytest.fixture
def wdb(db):
    """The rolled-back test connection, skipped until 005_wellness.sql is applied."""
    if db.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied to the test database")
    return db
