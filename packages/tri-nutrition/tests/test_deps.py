from tri_core.testing import ScriptedChatModel
from tri_nutrition.config import NutritionSettings
from tri_nutrition.graph.deps import make_deps


def test_make_deps_points_the_sql_tool_at_the_reader_role(monkeypatch):
    monkeypatch.delenv("TRI_READONLY_DATABASE_URL", raising=False)
    s = NutritionSettings(_env_file=None, database_url="postgresql://o:p@h:1/x")
    deps = make_deps(s, ScriptedChatModel(script=[]), None)
    assert deps.readonly_db_url == "postgresql://tri_reader:tri_reader@h:1/x"
