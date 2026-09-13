from tri_analyze.llm import MAX_TOKENS, make_model
from tri_core.config import Settings


def test_make_model_reads_model_and_max_tokens():
    m = make_model(Settings(_env_file=None, tri_model="claude-sonnet-5", anthropic_api_key="k"))
    assert m.model == "claude-sonnet-5"
    assert m.max_tokens == MAX_TOKENS == 16000
