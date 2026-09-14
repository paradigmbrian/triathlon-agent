"""The gate's server side: the change models' JSON schema for the form, and one validation path
for both editors. The same function guards POST /coach/review, so an edit that skips the client's
validate call still gets the same errors."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from tri_coach.models import Proposal
from tri_coach.repl import proposals_from_yaml, proposals_to_yaml
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange


class ValidationItem(BaseModel):
    loc: list[str | int]
    msg: str


class Validated(BaseModel):
    ok: bool
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[ValidationItem] = Field(default_factory=list)


def schema() -> dict[str, Any]:
    return {
        "proposal": Proposal.model_json_schema(),
        "planning_change": CalendarChange.model_json_schema(),
        "nutrition_change": NutritionChange.model_json_schema(),
    }


def _items(exc: ValidationError, prefix: list[str | int]) -> list[ValidationItem]:
    return [
        ValidationItem(loc=[*prefix, *e["loc"]], msg=e["msg"])
        for e in exc.errors(include_url=False)
    ]


def validate_json(items: list[dict[str, Any]]) -> Validated:
    typed_items: list[Proposal] = []
    errors: list[ValidationItem] = []
    for i, item in enumerate(items):
        # Validate domain explicitly since before validator runs first
        if (
            isinstance(item, dict)
            and "domain" in item
            and item["domain"] not in ["planning", "nutrition"]
        ):
            errors.append(
                ValidationItem(
                    loc=[i, "domain"],
                    msg="Input should be 'planning' or 'nutrition'",
                )
            )
            continue
        try:
            typed_items.append(Proposal.model_validate(item))
        except ValidationError as exc:
            errors.extend(_items(exc, [i]))
    if errors:
        return Validated(ok=False, errors=errors)
    return Validated(ok=True, proposals=[p.model_dump(mode="json") for p in typed_items])


def validate_yaml(text: str, originals: list[Proposal]) -> Validated:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return Validated(ok=False, errors=[ValidationItem(loc=["yaml"], msg=str(exc))])
    if doc is not None and not isinstance(doc, dict):
        return Validated(
            ok=False,
            errors=[ValidationItem(loc=["yaml"], msg="expected a mapping of id to proposal")],
        )
    try:
        typed_items = proposals_from_yaml(text, originals)
    except ValidationError as exc:
        return Validated(ok=False, errors=_items(exc, ["yaml"]))
    return Validated(ok=True, proposals=[p.model_dump(mode="json") for p in typed_items])


def to_yaml(proposals: list[Proposal]) -> str:
    return proposals_to_yaml(proposals)


def typed(v: Validated) -> list[Proposal]:
    return [Proposal.model_validate(p) for p in v.proposals]
