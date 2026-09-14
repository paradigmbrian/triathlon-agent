"""Request and response models for the routes; the frontend's types are generated from the
OpenAPI document these produce."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from tri_web.review import ValidationItem


class TurnIn(BaseModel):
    text: str = Field(min_length=1)


class ReviewIn(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    proposals: list[dict[str, Any]] | None = None


class ValidateIn(BaseModel):
    proposals: list[dict[str, Any]] | None = None
    yaml: str | None = None

    @model_validator(mode="after")
    def _one_of(self) -> ValidateIn:
        if (self.proposals is None) == (self.yaml is None):
            raise ValueError("send exactly one of proposals or yaml")
        return self


class SchemaOut(BaseModel):
    proposal: dict[str, Any]
    planning_change: dict[str, Any]
    nutrition_change: dict[str, Any]


class YamlOut(BaseModel):
    yaml: str


class Readiness(BaseModel):
    api_key: bool
    checkpointer: bool
    store: bool


class StatusOut(BaseModel):
    live: bool
    tools: list[str]
    ready: Readiness
    thread: str
    running: str | None


class NoReview(Exception):
    """Nothing is paused at the gate."""


class EditRejected(Exception):
    def __init__(self, errors: list[ValidationItem]) -> None:
        super().__init__("edit rejected")
        self.errors = errors
