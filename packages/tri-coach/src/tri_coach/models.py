"""The coach's vocabulary: briefs to sub-agents, their proposals, the change set at review."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange

Domain = Literal["planning", "nutrition"]


class Brief(BaseModel):
    domain: Domain
    instruction: str  # the coach's bounded instruction: signal, lever, constraint
    tool_call_id: str | None = None  # the consult_* call; None for the post-apply regenerate brief
    message_id: str | None = None  # the handoff ToolMessage the result replaces; None likewise
    regenerate: bool = False  # nutrition only: skip the sub-agent, go straight to targets


class Proposal(BaseModel):
    id: str  # "p1", "p2", ... within the turn
    domain: Domain
    summary: str  # the sub-graph's pending_summary
    changes: list[CalendarChange] | list[NutritionChange] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)  # last_error, then one line per key below
    # the sub-graph's pending_violations: planning by week_start ISO, nutrition by tp_workout_id
    # or "race"; check-in --yes leaves out the changes they cover
    pending_violations: dict[str, list[str]] = Field(default_factory=dict)
    question: str | None = None  # set instead of changes when the sub-agent asked
    overrides: dict[str, Any] | None = None  # nutrition: profile_overrides to persist on apply

    @model_validator(mode="before")
    @classmethod
    def _type_changes_by_domain(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
            return data
        model = CalendarChange if data.get("domain") == "planning" else NutritionChange
        typed = [c if isinstance(c, model) else model.model_validate(c) for c in data["changes"]]
        return {**data, "changes": typed}

    def render(self) -> str:
        if self.question is not None:
            return f"{self.id} ({self.domain}) asked instead of proposing: {self.question}"
        n = len(self.changes)
        lines = [
            f"{self.id} ({self.domain}): {self.summary}".rstrip(": "),
            f"{n} change{'' if n == 1 else 's'}",
        ]
        if self.violations:
            lines.append("violations: " + "; ".join(self.violations))
        return "\n".join(lines)


class ProposalRequest(BaseModel):
    narration: str
    ids: list[str]


class ChangeSet(BaseModel):
    narration: str  # the coach's explanation shown at review
    proposals: list[Proposal]


class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    proposals: list[Proposal] | None = None  # on edit: the YAML round trip, both domains


class ApplyReport(BaseModel):
    domain: Domain
    applied: int
    skipped: list[str]
    remaining: int
    error: str | None
    sessions_changed: bool  # planning: any create/update/delete/move applied
    applied_changes: list[str] = Field(default_factory=list)  # one line per change as written

    def line(self) -> str:
        parts = [f"applied {self.applied}"]
        if self.skipped:
            parts.append(f"skipped {len(self.skipped)}")
        if self.remaining:
            parts.append(f"{self.remaining} still pending")
        text = f"{self.domain}: " + ", ".join(parts)
        if self.error:
            text += f"; stopped: {self.error}"
        return "\n".join([text, *(f"  applied: {c}" for c in self.applied_changes)])
