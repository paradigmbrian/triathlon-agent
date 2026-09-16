"""What the page renders after a reload: the checkpoint's root messages as UiMessages, plus the
review that is paused or the change set that is held. The classification mirrors the stream's
(spec §5.3) so history and live events go through one component set."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from tri_coach.repl import paused_review
from tri_core.harness.messages import text_of

CONSULTS = {"consult_planning": "planning", "consult_nutrition": "nutrition"}
REPORT_PREFIXES = ("[review]", "[follow-on]", "Review rejected:")


class UiMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "activity", "consult", "report"]
    text: str
    where: str | None = None
    name: str | None = None
    args: dict[str, Any] | None = None
    chars: int | None = None


class ReviewPayload(BaseModel):
    narration: str
    proposals: list[dict[str, Any]]


class ThreadView(BaseModel):
    messages: list[UiMessage]
    paused: ReviewPayload | None
    held: ReviewPayload | None
    stuck: bool
    running: str | None


def ui_messages(messages: Sequence[BaseMessage]) -> list[UiMessage]:
    out: list[UiMessage] = []
    for i, m in enumerate(messages):
        mid = m.id or f"m{i}"
        text = text_of(m)
        if isinstance(m, HumanMessage):
            role: Literal["user", "report"] = (
                "report" if text.startswith(REPORT_PREFIXES) else "user"
            )
            out.append(UiMessage(id=mid, role=role, text=text))
        elif isinstance(m, AIMessage):
            if m.name == "apply":
                out.append(UiMessage(id=mid, role="report", text=text))
                continue
            for k, tc in enumerate(m.tool_calls):
                out.append(
                    UiMessage(
                        id=f"{mid}.{k}",
                        role="activity",
                        text=f"→ {tc['name']}",
                        where="coach",
                        name=tc["name"],
                        args=dict(tc["args"]),
                    )
                )
            if text:
                out.append(UiMessage(id=mid, role="assistant", text=text, where="coach"))
        elif isinstance(m, ToolMessage):
            domain = CONSULTS.get(m.name or "")
            if domain is not None:
                out.append(UiMessage(id=mid, role="consult", text=text, where=domain, name=m.name))
            else:
                out.append(
                    UiMessage(
                        id=mid,
                        role="activity",
                        text=f"← {m.name}: {len(text)} chars",
                        where="coach",
                        name=m.name,
                        chars=len(text),
                    )
                )
        # SystemMessage and anything else: skipped
    return out


def review_payload(raw: Any) -> ReviewPayload | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return ReviewPayload.model_validate(raw)
    return ReviewPayload(
        narration=raw.narration, proposals=[p.model_dump(mode="json") for p in raw.proposals]
    )


async def thread_snapshot(graph: Any, thread_id: str, *, running: str | None) -> ThreadView:
    snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    values = snap.values or {}
    paused = review_payload(paused_review(snap))
    held = review_payload(values.get("pending")) if paused is None else None
    stuck = paused is None and held is None and bool(snap.next)
    return ThreadView(
        messages=ui_messages(values.get("messages", [])),
        paused=paused,
        held=held,
        stuck=stuck,
        running=running,
    )
