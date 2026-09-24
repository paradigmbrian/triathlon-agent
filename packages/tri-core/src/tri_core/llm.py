"""Model routing: one model, effort, output ceiling and fallback chain per role.

Every role launches on today's model. A role moves to a lighter model or effort only after its
eval holds quality (docs/superpowers/specs/2026-09-15-model-routing-design.md §7.2); env vars
override one role at a time. A thread stays on one model, so the prompt cache keeps hitting.
When the primary model is overloaded or unavailable, the call is retried on the next Claude
model in the role's chain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from anthropic import (
    APIConnectionError,
    DeadlineExceededError,
    InternalServerError,
    OverloadedError,
    RateLimitError,
    ServiceUnavailableError,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from tri_core.config import Effort as Effort
from tri_core.config import Settings


class Role(StrEnum):
    COACH = "coach"
    ANALYST = "analyst"
    WELLNESS_CHAT = "wellness_chat"
    PLANNING_AGENT = "planning_agent"
    PLANNING_DESIGN = "planning_design"
    NUTRITION_AGENT = "nutrition_agent"
    NUTRITION_FUEL = "nutrition_fuel"
    LAB_EXTRACT = "lab_extract"
    LAB_REPORT = "lab_report"
    JUDGE = "judge"


@dataclass(frozen=True)
class ModelSpec:
    model: str
    effort: Effort | None  # None: the model's default (sends nothing)
    max_tokens: int
    fallbacks: tuple[str, ...]


ModelProvider = Callable[[Role], BaseChatModel]

_OPUS = "claude-opus-5"
_CHAIN = ("claude-opus-5", "claude-opus-4-8", "claude-sonnet-5")


def _spec(max_tokens: int = 16000) -> ModelSpec:
    return ModelSpec(model=_OPUS, effort=None, max_tokens=max_tokens, fallbacks=())


# Launch defaults: every role on today's model at its default effort. Change one line here only
# when that role's eval passes the gate in the spec's §7.2.
DEFAULTS: dict[Role, ModelSpec] = {
    Role.COACH: _spec(),
    Role.ANALYST: _spec(),
    Role.WELLNESS_CHAT: _spec(),
    Role.PLANNING_AGENT: _spec(),
    Role.PLANNING_DESIGN: _spec(),
    Role.NUTRITION_AGENT: _spec(),
    Role.NUTRITION_FUEL: _spec(),
    Role.LAB_EXTRACT: _spec(32000),  # a 200-row panel is roughly 12k output tokens as JSON
    Role.LAB_REPORT: _spec(32000),  # reports are long
    Role.JUDGE: _spec(),
}

# Roles that run structured output. It forces a tool call, which the API refuses when thinking
# is on, and an effort level turns thinking on; so these roles, and their fallbacks, never send
# an effort.
STRUCTURED_ROLES = frozenset(
    {Role.PLANNING_DESIGN, Role.NUTRITION_FUEL, Role.LAB_EXTRACT, Role.JUDGE}
)

# The errors worth retrying on another model: overload, rate limits, server errors and lost
# connections. A 400, 401, 403, 404 or 413 would fail the same way on any model.
RETRYABLE: tuple[type[BaseException], ...] = (
    RateLimitError,
    OverloadedError,
    InternalServerError,
    ServiceUnavailableError,
    DeadlineExceededError,
    APIConnectionError,
)


def _effort_levels(model_id: str) -> tuple[str, ...]:
    """The effort levels the model's profile lists; () for a model with no levels or profile."""
    profile = ChatAnthropic(model=model_id).profile or {}
    return tuple(profile.get("reasoning_effort_levels") or ())


def _env(role: Role) -> str:
    return role.value.upper()


def resolve(settings: Settings, role: Role) -> ModelSpec:
    default = DEFAULTS[role]
    role_model: str | None = getattr(settings, f"tri_model_{role.value}")
    role_effort: Effort | None = getattr(settings, f"tri_effort_{role.value}")
    model = role_model or settings.tri_model or default.model
    effort = role_effort or default.effort
    if settings.tri_model_fallbacks is not None:
        wanted = [m.strip() for m in settings.tri_model_fallbacks.split(",") if m.strip()]
    else:
        wanted = [m for m in _CHAIN if m != model][:2]
    fallbacks = tuple(dict.fromkeys(m for m in wanted if m != model))
    if effort is not None:
        if role in STRUCTURED_ROLES:
            raise ValueError(
                f"TRI_EFFORT_{_env(role)}={effort} is not allowed: {role.value} runs structured "
                "output, which cannot use thinking"
            )
        if effort not in _effort_levels(model):
            raise ValueError(f"TRI_EFFORT_{_env(role)}={effort} is not supported by {model}")
    return ModelSpec(model=model, effort=effort, max_tokens=default.max_tokens, fallbacks=fallbacks)


def make_model(settings: Settings, role: Role) -> ChatAnthropic:
    """The role's model. Raises ValueError for an invalid override, so a bad .env fails when the
    CLI or server starts, before any turn."""
    spec = resolve(settings, role)
    return ChatAnthropic(
        model=spec.model,
        max_tokens=spec.max_tokens,
        api_key=settings.anthropic_api_key,
        effort=spec.effort,
        metadata={"tri_role": role.value, "tri_fallbacks": list(spec.fallbacks)},
    )


def fallbacks_of(model: BaseChatModel) -> list[ChatAnthropic]:
    """The models to try, in order, when `model` fails with a RETRYABLE error. Empty for anything
    make_model did not build (fakes in tests, a model passed in by hand)."""
    if not isinstance(model, ChatAnthropic):
        return []
    meta = model.metadata or {}
    ids = meta.get("tri_fallbacks")
    if not ids:
        return []
    role = str(meta.get("tri_role", ""))
    out: list[ChatAnthropic] = []
    for model_id in ids:
        levels = _effort_levels(model_id)
        effort: Effort | None
        if role in STRUCTURED_ROLES:
            effort = None
        elif model.effort is not None and model.effort in levels:
            effort = model.effort
        elif levels:
            effort = "high"
        else:
            effort = None
        out.append(
            ChatAnthropic(
                model=model_id,
                max_tokens=model.max_tokens,
                api_key=model.anthropic_api_key,
                effort=effort,
                metadata={"tri_role": role, "tri_fallback_from": model.model},
            )
        )
    return out
