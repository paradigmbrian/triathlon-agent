"""The gate's server side: the change models' JSON schema for the form, and one validation path
for both editors. The same function guards POST /coach/review, so an edit that skips the client's
validate call still gets the same errors."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from tri_coach.models import Domain, Proposal
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


def _validate_proposal_item(item: Any, prefix: list[str | int]) -> list[ValidationItem]:
    """Validate a single proposal item dict with domain and changes.

    Returns list of ValidationItem errors. Validates in order:
    1. Item is a dict
    2. Domain field (using pydantic)
    3. Changes against the appropriate model (CalendarChange or NutritionChange)
    4. Full Proposal (for id, summary, etc.)
    """
    errors: list[ValidationItem] = []

    # Check if item is a dict
    if not isinstance(item, dict):
        return [ValidationItem(loc=prefix, msg="expected a mapping")]

    # Validate domain using TypeAdapter to get pydantic's validation
    domain_adapter: TypeAdapter[Domain] = TypeAdapter(Domain)
    try:
        domain = domain_adapter.validate_python(item.get("domain"))
    except ValidationError as exc:
        errors.extend(_items(exc, [*prefix, "domain"]))
        return errors

    # Validate changes against the appropriate model
    if isinstance(item.get("changes"), list):
        model = CalendarChange if domain == "planning" else NutritionChange
        for j, change in enumerate(item["changes"]):
            try:
                model.model_validate(change)
            except ValidationError as exc:
                errors.extend(_items(exc, [*prefix, "changes", j]))

    if errors:
        return errors

    # Validate full proposal for remaining fields (id, summary, etc.)
    try:
        Proposal.model_validate(item)
    except ValidationError as exc:
        errors.extend(_items(exc, prefix))

    return errors


def validate_json(items: list[dict[str, Any]]) -> Validated:
    typed_items: list[Proposal] = []
    errors: list[ValidationItem] = []
    for i, item in enumerate(items):
        item_errors = _validate_proposal_item(item, [i])
        if item_errors:
            errors.extend(item_errors)
        else:
            typed_items.append(Proposal.model_validate(item))
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

    # Validate each proposal in the YAML
    errors: list[ValidationItem] = []
    originals_by_id = {o.id: o for o in originals}

    if doc is None:
        doc = {}

    for pid, body in doc.items():
        pid_str = str(pid)
        # Check if body is a dict (or None, which means deletion)
        if body is not None and not isinstance(body, dict):
            errors.append(ValidationItem(loc=["yaml", pid_str], msg="expected a mapping"))
            continue

        # Build the merged dict (original + edited body)
        original = originals_by_id.get(pid_str)
        merged = {
            **(original.model_dump(mode="json") if original else {}),
            **(body or {}),
            "id": pid_str,
        }

        # Validate the merged proposal
        item_errors = _validate_proposal_item(merged, ["yaml", pid_str])
        errors.extend(item_errors)

    if errors:
        return Validated(ok=False, errors=errors)

    # On success, use proposals_from_yaml to get properly typed proposals
    try:
        typed_items = proposals_from_yaml(text, originals)
    except ValidationError as exc:
        return Validated(ok=False, errors=_items(exc, ["yaml"]))

    return Validated(ok=True, proposals=[p.model_dump(mode="json") for p in typed_items])


def to_yaml(proposals: list[Proposal]) -> str:
    return proposals_to_yaml(proposals)


def typed(v: Validated) -> list[Proposal]:
    return [Proposal.model_validate(p) for p in v.proposals]
