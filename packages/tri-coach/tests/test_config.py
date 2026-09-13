from pathlib import Path

from tri_coach.config import CoachSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_COACH_LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("TRI_COACH_MAX_CONSULTS_PER_DOMAIN", raising=False)
    s = CoachSettings(_env_file=None)
    assert s.tri_coach_langsmith_project == "tri_coach"
    assert s.tri_coach_max_consults_per_domain == 2
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_COACH_LANGSMITH_PROJECT", "coach-dev")
    monkeypatch.setenv("TRI_COACH_MAX_CONSULTS_PER_DOMAIN", "3")
    s = CoachSettings(_env_file=None)
    assert s.tri_coach_langsmith_project == "coach-dev"
    assert s.tri_coach_max_consults_per_domain == 3


def test_the_env_example_values_parse(monkeypatch):
    """A copied .env.example must not blow up at import time: a blank int is a ValidationError."""
    example = Path(__file__).resolve().parents[3] / ".env.example"
    for line in example.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith("TRI_COACH_"):
            monkeypatch.setenv(key, value)
    s = CoachSettings(_env_file=None)
    assert s.tri_coach_max_consults_per_domain == 2
    assert s.tri_coach_langsmith_project == "tri_coach"
