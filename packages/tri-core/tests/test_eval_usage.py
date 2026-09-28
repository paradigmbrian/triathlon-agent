import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage

from tri_core.eval_usage import (
    TokenCounts,
    UsageByRole,
    cost,
    counts_from,
    render_usage,
    with_usage,
)
from tri_core.llm import Role
from tri_core.testing import ScriptedChatModel


def reply(*, model="claude-opus-5", inp=1000, out=100, read=0) -> AIMessage:
    return AIMessage(
        "ok",
        usage_metadata={
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "input_token_details": {"cache_read": read, "cache_creation": 0},
        },
        response_metadata={"model_name": model},
    )


def test_counts_from_takes_cache_tokens_out_of_the_input_total():
    assert counts_from(
        {
            "input_tokens": 1000,
            "output_tokens": 50,
            "input_token_details": {"cache_read": 600, "cache_creation": 100},
        }
    ) == TokenCounts(input=300, output=50, cache_read=600, cache_write=100)
    # langchain-anthropic zeroes cache_creation when it splits writes by TTL
    assert counts_from(
        {
            "input_tokens": 1000,
            "output_tokens": 0,
            "input_token_details": {
                "cache_creation": 0,
                "ephemeral_5m_input_tokens": 200,
                "ephemeral_1h_input_tokens": 50,
            },
        }
    ) == TokenCounts(input=750, cache_write=250)
    assert counts_from({"input_tokens": 10, "output_tokens": 2}) == TokenCounts(input=10, output=2)


def test_cost_prices_each_kind_of_token():
    every = TokenCounts(
        input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000
    )
    assert cost("claude-opus-5", every) == pytest.approx(5 + 25 + 0.5 + 6.25)
    assert cost("claude-sonnet-5", TokenCounts(input=2_000_000)) == pytest.approx(4.0)
    assert cost("claude-unknown-9", every) is None


async def test_each_role_counts_its_own_calls_even_on_the_same_model():
    usage = UsageByRole()
    target = ScriptedChatModel(script=[reply(inp=1000, out=100), reply(inp=500, out=50, read=400)])
    judge = ScriptedChatModel(script=[reply(inp=200, out=20)])
    models = with_usage(lambda role: {Role.ANALYST: target, Role.JUDGE: judge}[role], usage)
    t, j = models(Role.ANALYST), models(Role.JUDGE)
    await t.ainvoke("a")
    await t.ainvoke("b")
    await j.ainvoke("c")
    assert usage.by_role() == {
        "analyst": {"claude-opus-5": TokenCounts(input=1100, output=150, cache_read=400)},
        "judge": {"claude-opus-5": TokenCounts(input=200, output=20)},
    }


def test_a_reply_without_usage_adds_nothing():
    usage = UsageByRole()
    model = with_usage(lambda role: ScriptedChatModel(script=[AIMessage("x")]), usage)(Role.JUDGE)
    model.invoke("q")
    assert usage.by_role() == {}


def test_a_model_shared_by_two_roles_reports_under_the_last_one_asked_for():
    usage = UsageByRole()
    shared = ScriptedChatModel(script=[reply()])
    models = with_usage(lambda role: shared, usage)
    models(Role.ANALYST)
    models(Role.ANALYST)
    models(Role.JUDGE)
    assert shared.callbacks == [usage.handler("judge")]
    shared.invoke("q")
    assert list(usage.by_role()) == ["judge"]


def test_other_callbacks_on_the_model_are_kept():
    other = BaseCallbackHandler()
    model = ScriptedChatModel(script=[], callbacks=[other])
    with_usage(lambda role: model, UsageByRole())(Role.COACH)
    assert isinstance(model.callbacks, list)
    assert model.callbacks[0] is other and len(model.callbacks) == 2


def test_a_failing_collector_never_fails_the_model_call(monkeypatch):
    usage = UsageByRole()

    def boom(*args):
        raise RuntimeError("collector broke")

    monkeypatch.setattr(usage, "add", boom)
    model = with_usage(lambda role: ScriptedChatModel(script=[reply()]), usage)(Role.JUDGE)
    assert model.invoke("q").content == "ok"


def test_the_usage_line_splits_roles_and_totals():
    usage = UsageByRole()
    usage.add(
        "analyst", "claude-opus-5", TokenCounts(input=100_000, output=40_000, cache_read=300_000)
    )
    usage.add("judge", "claude-opus-5", TokenCounts(input=96_000, output=8_000))
    assert render_usage(usage) == (
        "usage: analyst 400k in / 40k out (cache read 300k) $1.65"
        " · judge 96k in / 8.0k out $0.68 · total $2.33"
    )


def test_an_unknown_model_shows_a_question_mark_and_so_does_the_total():
    usage = UsageByRole()
    usage.add("judge", "claude-next-9", TokenCounts(input=1000, output=10))
    usage.add("analyst", "claude-opus-5", TokenCounts(input=1000, output=10))
    line = render_usage(usage)
    assert "judge 1.0k in / 10 out $?" in line and line.endswith("total $?")
    record = usage.as_record()
    assert record["roles"]["judge"]["cost"] is None and record["total_cost"] is None


def test_no_calls_says_so():
    assert render_usage(UsageByRole()) == "usage: no model calls"
    assert UsageByRole().as_record() == {"roles": {}, "total_cost": 0.0}


def test_the_record_names_the_models_and_sums_the_counts():
    usage = UsageByRole()
    usage.add(
        "analyst", "claude-opus-5", TokenCounts(input=100_000, output=40_000, cache_read=300_000)
    )
    usage.add("analyst", "claude-sonnet-5", TokenCounts(input=1_000_000))
    record = usage.as_record()
    assert record["roles"]["analyst"] == {
        "model": "claude-opus-5, claude-sonnet-5",
        "input": 1_100_000,
        "output": 40_000,
        "cache_read": 300_000,
        "cache_write": 0,
        "cost": 3.65,
    }
    assert record["total_cost"] == 3.65


def test_a_dated_or_provider_prefixed_model_id_is_priced_as_its_base_model():
    counts = TokenCounts(input=1_000_000, output=100_000)
    base = cost("claude-opus-5", counts)
    assert cost("claude-opus-5-20261001", counts) == base
    assert cost("claude-opus-5@20261001", counts) == base
    assert cost("anthropic.claude-opus-5", counts) == base
    assert cost("us.anthropic.claude-opus-5-v1:0", counts) == base
    # a different model that merely starts with a priced id is not that model
    assert cost("claude-opus-5-5", counts) is None
