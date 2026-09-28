"""Token usage and estimated cost per model role for one eval run. Every model a run builds
reports its responses' usage here under the role it was built for, so the target's tokens and
the judge's are counted apart even when both run on the same model
(docs/superpowers/specs/2026-09-28-eval-cost-design.md §3)."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tri_core.llm import ModelProvider, Role

CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.1


@dataclass(frozen=True)
class Price:
    """US$ per million tokens."""

    input: float
    output: float


# Anthropic first-party list prices, checked 2026-09-28. A model missing here costs `$?`.
PRICES: dict[str, Price] = {
    "claude-opus-5": Price(5.0, 25.0),
    "claude-opus-4-8": Price(5.0, 25.0),
    "claude-sonnet-5": Price(2.0, 10.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
}


@dataclass
class TokenCounts:
    """`input` is the uncached input; cache reads and writes are counted apart."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, other: TokenCounts) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    @property
    def total_input(self) -> int:
        return self.input + self.cache_read + self.cache_write


def counts_from(usage: Mapping[str, Any]) -> TokenCounts:
    """LangChain's `usage_metadata` as counts. langchain-anthropic's `input_tokens` already
    includes cache reads and writes, and a write comes either as `cache_creation` or split by TTL
    (with `cache_creation` zeroed); the uncached part is what is left."""
    details = usage.get("input_token_details") or {}
    read = int(details.get("cache_read") or 0)
    write = sum(
        int(details.get(key) or 0)
        for key in ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
    )
    total = int(usage.get("input_tokens") or 0)
    return TokenCounts(
        input=max(total - read - write, 0),
        output=int(usage.get("output_tokens") or 0),
        cache_read=read,
        cache_write=write,
    )


# What the API may wrap around a priced id: a provider prefix (`us.anthropic.`) before it, and a
# snapshot date (`-20261001`, `@20261001`) or provider version (`-v1:0`) after it.
_MODEL_ID = re.compile(r"^(?:[\w.]+\.)?(claude-[a-z0-9-]+?)(?:[-@]\d{8})?(?:-v\d+(?::\d+)?)?$")


def price_for(model: str) -> Price | None:
    """The price of `model`, by exact id or by the priced id inside a dated or provider-prefixed
    one (the response's model id is priced, not the requested one). A different model that only
    starts with a priced id (`claude-opus-5-5`) has no price."""
    if model in PRICES:
        return PRICES[model]
    match = _MODEL_ID.match(model)
    return PRICES.get(match.group(1)) if match else None


def cost(model: str, counts: TokenCounts) -> float | None:
    """Estimated US$ for `counts` on `model`; None when the model has no price."""
    price = price_for(model)
    if price is None:
        return None
    return (
        counts.input * price.input
        + counts.cache_write * price.input * CACHE_WRITE_FACTOR
        + counts.cache_read * price.input * CACHE_READ_FACTOR
        + counts.output * price.output
    ) / 1_000_000


class _RoleHandler(BaseCallbackHandler):
    """Adds each response's usage to `collector` under `role`. Errors in a handler are logged
    by LangChain and never fail the model call (`raise_error` stays False)."""

    def __init__(self, collector: UsageByRole, role: str) -> None:
        super().__init__()
        self.collector = collector
        self.role = role

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                if not isinstance(generation, ChatGeneration):
                    continue
                message = generation.message
                if not isinstance(message, AIMessage) or not message.usage_metadata:
                    continue
                meta = message.response_metadata or {}
                model = str(meta.get("model_name") or meta.get("model") or "?")
                self.collector.add(self.role, model, counts_from(message.usage_metadata))


class UsageByRole:
    """Sums per role and model, in first-use order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, TokenCounts]] = {}
        self._handlers: dict[str, _RoleHandler] = {}

    def handler(self, role: str) -> BaseCallbackHandler:
        with self._lock:
            if role not in self._handlers:
                self._handlers[role] = _RoleHandler(self, role)
            return self._handlers[role]

    def add(self, role: str, model: str, counts: TokenCounts) -> None:
        with self._lock:
            self._counts.setdefault(role, {}).setdefault(model, TokenCounts()).add(counts)

    def by_role(self) -> dict[str, dict[str, TokenCounts]]:
        with self._lock:
            return {
                role: {model: TokenCounts(**vars(c)) for model, c in models.items()}
                for role, models in self._counts.items()
            }

    def as_record(self) -> dict[str, Any]:
        """For the results file: per role its model(s), the four counts and the cost (None when
        a model has no price), and the total (None when any cost is)."""
        roles: dict[str, Any] = {}
        total: float | None = 0.0
        for role, models in self.by_role().items():
            summed = TokenCounts()
            role_cost: float | None = 0.0
            for model, counts in models.items():
                summed.add(counts)
                c = cost(model, counts)
                role_cost = None if role_cost is None or c is None else role_cost + c
            roles[role] = {
                "model": ", ".join(models),
                **vars(summed),
                "cost": None if role_cost is None else round(role_cost, 4),
            }
            total = None if total is None or role_cost is None else total + role_cost
        return {"roles": roles, "total_cost": None if total is None else round(total, 4)}


def with_usage(models: ModelProvider, usage: UsageByRole) -> ModelProvider:
    """`models` with every model it returns reporting to `usage` under the role it was asked
    for. A model object handed out for two roles reports under the last one (make_model builds a
    new model per call; tests often share one fake)."""

    def provide(role: Role) -> BaseChatModel:
        model = models(role)
        handler = usage.handler(role.value)
        current = model.callbacks
        if current is None or isinstance(current, list):
            kept = [
                h
                for h in (current or [])
                if not (isinstance(h, _RoleHandler) and h.collector is usage)
            ]
            model.callbacks = [*kept, handler]
        else:
            current.add_handler(handler, inherit=False)
        return model

    return provide


def _tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 10_000:
        return f"{n / 1000:.1f}k"
    return f"{round(n / 1000)}k"


def _usd(value: float | None) -> str:
    return "$?" if value is None else f"${value:.2f}"


def render_usage(usage: UsageByRole) -> str:
    record = usage.as_record()
    if not record["roles"]:
        return "usage: no model calls"
    parts = []
    for role, r in record["roles"].items():
        text = (
            f"{role} {_tokens(r['input'] + r['cache_read'] + r['cache_write'])} in"
            f" / {_tokens(r['output'])} out"
        )
        if r["cache_read"]:
            text += f" (cache read {_tokens(r['cache_read'])})"
        parts.append(f"{text} {_usd(r['cost'])}")
    return "usage: " + " · ".join(parts) + f" · total {_usd(record['total_cost'])}"
