import anthropic
import httpx
import pytest

from tri_core.harness.turns import (
    TurnFailure,
    api_error_message,
    format_failure,
    stream_turn,
    turn_config,
)

REQ = httpx.Request("POST", "https://api.anthropic.com")
INGEST_HINT = "Wait a moment and rerun; the thread resumes."


def rate_limited() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(
        message="slow down", response=httpx.Response(429, request=REQ), body=None
    )


def server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError(
        message="boom", response=httpx.Response(500, request=REQ), body=None
    )


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=REQ)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_event(self, namespace, mode, data) -> None:
        self.events.append((namespace, mode, data))


class ScriptedRunnable:
    """astream yields the given items, then raises `error` if one is set; records its kwargs."""

    def __init__(self, items, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.kwargs: dict | None = None

    async def astream(self, payload, **kwargs):
        self.kwargs = kwargs
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def test_api_error_message_matches_todays_sentences():
    assert api_error_message(rate_limited()) == (
        "rate limited: slow down. Wait a moment and try again."
    )
    assert api_error_message(rate_limited(), rate_limit_hint=INGEST_HINT) == (
        "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    )
    assert api_error_message(server_error()) == "Anthropic API error 500: boom"
    assert api_error_message(connection_error()) == (
        "connection error talking to Anthropic: Connection error."
    )
    assert api_error_message(RuntimeError("x")) is None


def test_turn_config_adds_the_limit_and_tags_only_when_given():
    assert turn_config("t") == {"configurable": {"thread_id": "t"}}
    assert turn_config("t", tags=[]) == {"configurable": {"thread_id": "t"}}
    assert turn_config("coach", tags=("checkin",), recursion_limit=60) == {
        "configurable": {"thread_id": "coach"},
        "recursion_limit": 60,
        "tags": ["checkin"],
    }


async def test_stream_turn_normalises_subgraph_items():
    runnable = ScriptedRunnable([(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})])
    sink = Recorder()
    cfg = turn_config("t")
    assert await stream_turn(runnable, {"messages": []}, cfg, sink, subgraphs=True) is None
    assert sink.events == [(("intake:1",), "messages", "m"), ((), "updates", {"a": 1})]
    assert runnable.kwargs == {
        "config": cfg,
        "stream_mode": ["messages", "updates"],
        "subgraphs": True,
    }


async def test_stream_turn_normalises_list_mode_items_and_passes_context_when_set():
    runnable = ScriptedRunnable([("messages", "m"), ("updates", {"b": 2})])
    sink = Recorder()
    ctx = object()
    await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False, context=ctx)
    assert sink.events == [((), "messages", "m"), ((), "updates", {"b": 2})]
    assert runnable.kwargs["context"] is ctx and "subgraphs" not in runnable.kwargs


async def test_stream_turn_normalises_single_mode_items():
    runnable = ScriptedRunnable([{"extract": {}}, {"store": {"panel_id": 3}}])
    sink = Recorder()
    await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False, stream_mode="updates")
    assert sink.events == [
        ((), "updates", {"extract": {}}),
        ((), "updates", {"store": {"panel_id": 3}}),
    ]
    assert runnable.kwargs["stream_mode"] == "updates" and "context" not in runnable.kwargs


async def test_stream_turn_returns_a_failure_for_anthropic_errors_after_earlier_events():
    runnable = ScriptedRunnable([("updates", {"a": 1})], error=connection_error())
    sink = Recorder()
    failure = await stream_turn(runnable, {}, turn_config("t"), sink, subgraphs=False)
    assert isinstance(failure, TurnFailure)
    assert isinstance(failure.exc, anthropic.APIConnectionError)
    assert failure.message == "connection error talking to Anthropic: Connection error."
    assert len(sink.events) == 1
    assert format_failure(failure) == (
        "\n[connection error talking to Anthropic: Connection error.]\n"
    )


async def test_stream_turn_propagates_other_errors_unless_catch_all_is_set():
    with pytest.raises(RuntimeError, match="kaboom"):
        await stream_turn(
            ScriptedRunnable([], error=RuntimeError("kaboom")),
            {},
            turn_config("t"),
            Recorder(),
            subgraphs=True,
        )
    failure = await stream_turn(
        ScriptedRunnable([], error=RuntimeError("kaboom")),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=True,
        catch_all="ingest failed",
    )
    assert failure is not None and failure.message == "ingest failed: RuntimeError: kaboom"


async def test_stream_turn_uses_the_rate_limit_hint():
    failure = await stream_turn(
        ScriptedRunnable([], error=rate_limited()),
        {},
        turn_config("t"),
        Recorder(),
        subgraphs=False,
        rate_limit_hint=INGEST_HINT,
    )
    assert failure is not None
    assert (
        failure.message == "rate limited: slow down. Wait a moment and rerun; the thread resumes."
    )
