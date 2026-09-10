from tri_nutrition.config import NutritionSettings


def test_defaults(monkeypatch):
    monkeypatch.delenv("TRI_NUTRITION_HORIZON_DAYS", raising=False)
    monkeypatch.delenv("TRI_NUTRITION_LANGSMITH_PROJECT", raising=False)
    s = NutritionSettings(_env_file=None)
    assert s.tri_nutrition_horizon_days == 14
    assert s.tri_nutrition_langsmith_project == "tri_nutrition"
    assert s.database_url.endswith("/tri_analyze")  # inherited from tri_core Settings


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRI_NUTRITION_HORIZON_DAYS", "7")
    assert NutritionSettings(_env_file=None).tri_nutrition_horizon_days == 7
