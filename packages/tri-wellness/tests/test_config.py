import pytest
from pydantic import ValidationError

from tri_wellness.config import WellnessSettings


def test_defaults(monkeypatch):
    monkeypatch.setenv("TRI_ATHLETE_SEX", "male")
    monkeypatch.delenv("TRI_WELLNESS_LANGSMITH_PROJECT", raising=False)
    s = WellnessSettings(_env_file=None)
    assert s.tri_athlete_sex == "male"
    assert s.tri_wellness_langsmith_project == "tri_wellness"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_sex_is_required_and_validated(monkeypatch):
    monkeypatch.delenv("TRI_ATHLETE_SEX", raising=False)
    with pytest.raises(ValidationError):
        WellnessSettings(_env_file=None)
    monkeypatch.setenv("TRI_ATHLETE_SEX", "other")
    with pytest.raises(ValidationError):
        WellnessSettings(_env_file=None)


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_ATHLETE_SEX", "female")
    monkeypatch.setenv("TRI_WELLNESS_LANGSMITH_PROJECT", "labs")
    s = WellnessSettings(_env_file=None)
    assert s.tri_athlete_sex == "female"
    assert s.tri_wellness_langsmith_project == "labs"
