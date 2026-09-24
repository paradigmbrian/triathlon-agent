import logging
from typing import Any

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphBubbleUp
from pydantic import BaseModel

import tri_core.llm as llm
from tri_core.config import Settings
from tri_core.llm import (
    DEFAULTS,
    STRUCTURED_ROLES,
    Role,
    claude_fallback,
    fallbacks_of,
    make_model,
    resolve,
    streaming,
    structured,
)
from tri_core.testing import ScriptedChatModel, tool_call


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, anthropic_api_key="k", **kw)


# resolve


def test_every_role_launches_on_opus_5_at_default_effort():
    assert set(DEFAULTS) == set(Role)
    for role in Role:
        spec = resolve(settings(), role)
        assert spec.model == "claude-opus-5" and spec.effort is None
        assert spec.fallbacks == ("claude-opus-4-8", "claude-sonnet-5")
    assert resolve(settings(), Role.LAB_EXTRACT).max_tokens == 32000
    assert resolve(settings(), Role.LAB_REPORT).max_tokens == 32000
    assert resolve(settings(), Role.COACH).max_tokens == 16000


def test_role_override_beats_tri_model_which_beats_the_default():
    s = settings(tri_model="claude-sonnet-5", tri_model_analyst="claude-haiku-4-5")
    assert resolve(s, Role.ANALYST).model == "claude-haiku-4-5"
    assert resolve(s, Role.COACH).model == "claude-sonnet-5"


def test_effort_override_applies_and_a_model_override_does_not_reset_it():
    s = settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium")
    assert resolve(s, Role.ANALYST).effort == "medium"
    assert resolve(settings(tri_effort_coach="high"), Role.COACH).effort == "high"


def test_default_chain_is_the_first_two_other_models():
    assert resolve(settings(tri_model="claude-opus-4-8"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-sonnet-5",
    )
    assert resolve(settings(tri_model="claude-sonnet-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )
    assert resolve(settings(tri_model="claude-haiku-4-5"), Role.COACH).fallbacks == (
        "claude-opus-5",
        "claude-opus-4-8",
    )


def test_tri_model_fallbacks_is_parsed_and_drops_the_primary():
    s = settings(tri_model_fallbacks=" claude-sonnet-5 , claude-opus-5,claude-sonnet-5 ")
    assert resolve(s, Role.COACH).fallbacks == ("claude-sonnet-5",)
    assert resolve(settings(tri_model_fallbacks=""), Role.COACH).fallbacks == ()


def test_an_effort_the_model_does_not_list_raises_naming_the_env_var():
    s = settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low")
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST=low is not supported by claude-haiku"):
        resolve(s, Role.ANALYST)
    assert resolve(settings(tri_model_analyst="claude-haiku-4-5"), Role.ANALYST).effort is None


def test_structured_roles_refuse_an_effort():
    assert {
        Role.PLANNING_DESIGN,
        Role.NUTRITION_FUEL,
        Role.LAB_EXTRACT,
        Role.JUDGE,
    } == STRUCTURED_ROLES
    with pytest.raises(ValueError, match="TRI_EFFORT_JUDGE=low is not allowed"):
        resolve(settings(tri_effort_judge="low"), Role.JUDGE)
    with pytest.raises(ValueError, match="TRI_EFFORT_NUTRITION_FUEL=medium is not allowed"):
        resolve(settings(tri_effort_nutrition_fuel="medium"), Role.NUTRITION_FUEL)


# make_model


def test_make_model_builds_the_role_spec_with_its_metadata():
    m = make_model(
        settings(tri_model_analyst="claude-sonnet-5", tri_effort_analyst="medium"), Role.ANALYST
    )
    assert m.model == "claude-sonnet-5" and m.max_tokens == 16000 and m.effort == "medium"
    assert m.anthropic_api_key.get_secret_value() == "k"
    meta = m.metadata or {}
    assert meta["tri_role"] == "analyst"
    assert meta["tri_fallbacks"] == ["claude-opus-5", "claude-opus-4-8"]
    lab = make_model(settings(), Role.LAB_EXTRACT)
    assert lab.max_tokens == 32000 and lab.effort is None


def test_make_model_raises_before_any_call_for_a_bad_override():
    with pytest.raises(ValueError, match="TRI_EFFORT_ANALYST"):
        make_model(
            settings(tri_model_analyst="claude-haiku-4-5", tri_effort_analyst="low"), Role.ANALYST
        )


# fallbacks_of


def test_fallbacks_of_is_empty_for_models_make_model_did_not_build():
    from langchain_anthropic import ChatAnthropic

    assert fallbacks_of(ScriptedChatModel(script=[])) == []
    assert fallbacks_of(ChatAnthropic(model="claude-opus-5")) == []
    assert fallbacks_of(make_model(settings(tri_model_fallbacks=""), Role.COACH)) == []


def test_fallbacks_of_builds_each_model_with_its_own_profile_and_effort():
    primary = make_model(settings(), Role.COACH)
    fbs = fallbacks_of(primary)
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert [f.effort for f in fbs] == ["high", "high"]  # primary at default: run fallbacks at high
    assert all(f.max_tokens == 16000 for f in fbs)
    assert all(f.anthropic_api_key.get_secret_value() == "k" for f in fbs)
    assert all((f.metadata or {})["tri_fallback_from"] == "claude-opus-5" for f in fbs)
    assert all((f.metadata or {})["tri_role"] == "coach" for f in fbs)


def test_fallbacks_keep_the_primary_effort_when_listed_and_drop_it_for_haiku():
    s = settings(
        tri_effort_analyst="medium", tri_model_fallbacks="claude-sonnet-5,claude-haiku-4-5"
    )
    fbs = fallbacks_of(make_model(s, Role.ANALYST))
    assert [(f.model, f.effort) for f in fbs] == [
        ("claude-sonnet-5", "medium"),
        ("claude-haiku-4-5", None),
    ]


def test_structured_roles_fall_back_without_effort():
    fbs = fallbacks_of(make_model(settings(), Role.NUTRITION_FUEL))
    assert [f.model for f in fbs] == ["claude-opus-4-8", "claude-sonnet-5"]
    assert all(f.effort is None for f in fbs)


REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def overloaded() -> anthropic.OverloadedError:
    return anthropic.OverloadedError(
        "overloaded", response=httpx.Response(529, request=REQ), body=None
    )


def bad_request() -> anthropic.BadRequestError:
    return anthropic.BadRequestError("bad", response=httpx.Response(400, request=REQ), body=None)


# claude_fallback


class FakeRequest:
    def __init__(self, model: Any) -> None:
        self.model = model

    def override(self, **kw: Any) -> "FakeRequest":
        return FakeRequest(kw["model"])


def recording_handler(errors: dict[str, BaseException]):
    seen: list[str] = []

    async def handler(request: FakeRequest) -> str:
        seen.append(request.model.model)
        if request.model.model in errors:
            raise errors[request.model.model]
        return f"answered by {request.model.model}"

    return handler, seen


async def test_claude_fallback_moves_to_the_next_model_on_overload(caplog):
    handler, seen = recording_handler({"claude-opus-5": overloaded()})
    primary = make_model(settings(), Role.COACH)
    with caplog.at_level(logging.WARNING, logger="tri_core.llm"):
        out = await claude_fallback.awrap_model_call(FakeRequest(primary), handler)
    assert out == "answered by claude-opus-4-8"
    assert seen == ["claude-opus-5", "claude-opus-4-8"]
    assert "coach fell back from claude-opus-5 to claude-opus-4-8 after OverloadedError" in (
        caplog.text
    )


async def test_claude_fallback_raises_a_bad_request_without_retrying():
    handler, seen = recording_handler({"claude-opus-5": bad_request()})
    with pytest.raises(anthropic.BadRequestError):
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert seen == ["claude-opus-5"]


async def test_claude_fallback_lets_graph_control_flow_through():
    handler, seen = recording_handler({"claude-opus-5": GraphBubbleUp()})
    with pytest.raises(GraphBubbleUp):
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert seen == ["claude-opus-5"]


async def test_claude_fallback_raises_the_last_error_when_every_model_fails():
    last = overloaded()
    errors = {
        "claude-opus-5": overloaded(),
        "claude-opus-4-8": overloaded(),
        "claude-sonnet-5": last,
    }
    handler, seen = recording_handler(errors)
    with pytest.raises(anthropic.OverloadedError) as info:
        await claude_fallback.awrap_model_call(
            FakeRequest(make_model(settings(), Role.COACH)), handler
        )
    assert info.value is last and len(seen) == 3


async def test_claude_fallback_without_fallbacks_raises_the_original_error():
    first = overloaded()
    handler, seen = recording_handler({"claude-opus-5": first})
    model = make_model(settings(tri_model_fallbacks=""), Role.COACH)
    with pytest.raises(anthropic.OverloadedError) as info:
        await claude_fallback.awrap_model_call(FakeRequest(model), handler)
    assert info.value is first and seen == ["claude-opus-5"]


def test_claude_fallback_has_a_sync_hook_too():
    def handler(request: FakeRequest) -> str:
        if request.model.model == "claude-opus-5":
            raise overloaded()
        return request.model.model

    out = claude_fallback.wrap_model_call(FakeRequest(make_model(settings(), Role.COACH)), handler)
    assert out == "claude-opus-4-8"


# structured and streaming


class Verdict(BaseModel):
    ok: bool


class Raising(ScriptedChatModel):
    """A fake that fails every call with `error` before producing anything."""

    error: Any = None

    def _generate(self, *a: Any, **k: Any) -> Any:
        raise self.error

    def _stream(self, *a: Any, **k: Any) -> Any:
        raise self.error


def with_fallbacks_to(monkeypatch, *fallbacks: Any) -> None:
    monkeypatch.setattr(llm, "fallbacks_of", lambda model: list(fallbacks))


async def test_structured_falls_back_on_a_retryable_error(monkeypatch):
    backup = ScriptedChatModel(script=[tool_call("Verdict", {"ok": True})])
    with_fallbacks_to(monkeypatch, backup)
    runnable = structured(Raising(script=[], error=overloaded()), Verdict)
    assert await runnable.ainvoke([HumanMessage("judge")]) == Verdict(ok=True)


async def test_structured_does_not_fall_back_on_a_bad_request(monkeypatch):
    backup = ScriptedChatModel(script=[tool_call("Verdict", {"ok": True})])
    with_fallbacks_to(monkeypatch, backup)
    with pytest.raises(anthropic.BadRequestError):
        await structured(Raising(script=[], error=bad_request()), Verdict).ainvoke(
            [HumanMessage("x")]
        )
    assert backup.calls == 0


async def test_structured_raises_the_primary_error_when_every_model_fails(monkeypatch):
    first = overloaded()
    with_fallbacks_to(monkeypatch, Raising(script=[], error=overloaded()))
    with pytest.raises(anthropic.OverloadedError) as info:
        await structured(Raising(script=[], error=first), Verdict).ainvoke([HumanMessage("x")])
    assert info.value is first


def test_structured_without_fallbacks_is_the_plain_structured_model():
    model = ScriptedChatModel(script=[tool_call("Verdict", {"ok": False})])
    assert structured(model, Verdict).invoke([HumanMessage("x")]) == Verdict(ok=False)


async def test_streaming_falls_back_before_the_first_chunk(monkeypatch):
    with_fallbacks_to(monkeypatch, ScriptedChatModel(script=[AIMessage(content="from backup")]))
    chunks = [c async for c in streaming(Raising(script=[], error=overloaded())).astream("hi")]
    assert "".join(str(c.content) for c in chunks) == "from backup"


async def test_streaming_does_not_fall_back_on_a_bad_request(monkeypatch):
    backup = ScriptedChatModel(script=[AIMessage(content="x")])
    with_fallbacks_to(monkeypatch, backup)
    with pytest.raises(anthropic.BadRequestError):
        [c async for c in streaming(Raising(script=[], error=bad_request())).astream("hi")]
    assert backup.calls == 0


def test_streaming_without_fallbacks_is_the_model_itself():
    model = ScriptedChatModel(script=[])
    assert streaming(model) is model
