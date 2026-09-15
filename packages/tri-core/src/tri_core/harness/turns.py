"""The turn driver every REPL shares: one stream loop that feeds a sink, and the sentences an
Anthropic error becomes. The loop never prints; the drivers decide how a failure reads."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

Out = Callable[[str], None]

DEFAULT_RATE_LIMIT_HINT = "Wait a moment and try again."
DEFAULT_STREAM_MODES = ("messages", "updates")


class TurnSink(Protocol):
    def on_event(self, namespace: tuple[str, ...], mode: str, data: Any) -> None: ...


@dataclass(frozen=True)
class TurnFailure:
    exc: Exception
    message: str  # no brackets or newlines


def api_error_message(
    exc: BaseException, *, rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT
) -> str | None:
    """The sentence for an Anthropic error, or None for anything else. RateLimitError is an
    APIStatusError, so it is checked first."""
    if isinstance(exc, anthropic.RateLimitError):
        return f"rate limited: {exc}. {rate_limit_hint}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return f"connection error talking to Anthropic: {exc}"
    return None


def turn_config(
    thread_id: str, *, tags: Sequence[str] | None = None, recursion_limit: int | None = None
) -> dict[str, Any]:
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if recursion_limit is not None:
        cfg["recursion_limit"] = recursion_limit
    if tags:
        cfg["tags"] = list(tags)
    return cfg


async def stream_turn(
    runnable: Any,
    payload: Any,
    config: dict[str, Any],
    sink: TurnSink,
    *,
    subgraphs: bool,
    stream_mode: str | Sequence[str] | None = None,
    context: Any = None,
    catch_all: str | None = None,
    rate_limit_hint: str = DEFAULT_RATE_LIMIT_HINT,
) -> TurnFailure | None:
    """Stream one run into `sink` as (namespace, mode, data). An Anthropic error, or any error
    when `catch_all` names the failure, ends the run as a TurnFailure; anything else propagates.
    `subgraphs` and `context` reach astream only when set."""
    mode: str | list[str]
    if stream_mode is None:
        mode = list(DEFAULT_STREAM_MODES)
    elif isinstance(stream_mode, str):
        mode = stream_mode
    else:
        mode = list(stream_mode)
    kwargs: dict[str, Any] = {"config": config, "stream_mode": mode}
    if subgraphs:
        kwargs["subgraphs"] = True
    if context is not None:
        kwargs["context"] = context
    try:
        async for item in runnable.astream(payload, **kwargs):
            if subgraphs:
                namespace, event_mode, data = item
                sink.on_event(tuple(namespace), event_mode, data)
            elif isinstance(mode, str):
                sink.on_event((), mode, item)
            else:
                event_mode, data = item
                sink.on_event((), event_mode, data)
    except Exception as exc:
        message = api_error_message(exc, rate_limit_hint=rate_limit_hint)
        if message is None:
            if catch_all is None:
                raise
            message = f"{catch_all}: {type(exc).__name__}: {exc}"
        return TurnFailure(exc, message)
    return None


def format_failure(failure: TurnFailure) -> str:
    """How a REPL prints a failed turn: on its own bracketed line."""
    return f"\n[{failure.message}]\n"
