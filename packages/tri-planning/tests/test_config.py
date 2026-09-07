from tri_planning.config import PlanningSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_PLANNING_HORIZON_WEEKS", raising=False)
    s = PlanningSettings(_env_file=None)
    assert s.tri_planning_horizon_weeks == 3
    assert s.tri_planning_langsmith_project == "tri-planning"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_PLANNING_HORIZON_WEEKS", "2")
    assert PlanningSettings(_env_file=None).tri_planning_horizon_weeks == 2
