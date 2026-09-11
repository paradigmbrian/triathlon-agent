"""Loads and validates markers.yaml into MarkerSpec models and an alias index.

The YAML is the unresolved form: a range block is either `{low, high}` or
`{male: {low, high}, female: {low, high}}`. The registry resolves it for one sex at load time, so
nothing downstream knows about sex-specific ranges. Validation fails on import naming the marker
and the field, so a typo in the table fails the test suite.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from tri_wellness.config import Sex
from tri_wellness.labs.models import Confounder

MARKERS_PATH = Path(__file__).with_name("markers.yaml")

SYSTEMS: frozenset[str] = frozenset(
    {
        "iron",
        "thyroid",
        "metabolic",
        "lipids",
        "inflammation",
        "liver",
        "kidney",
        "cbc",
        "hormones",
        "vitamins_minerals",
        "electrolytes",
    }
)

Direction = Literal["low", "high", "both"]


class RegistryError(ValueError):
    """markers.yaml is invalid. The message names the marker and the field."""


class Range(BaseModel):
    low: float | None = None
    high: float | None = None


class RawMarkerEntry(BaseModel):
    """One YAML entry before sex resolution. Range blocks are validated in `_resolve_range`."""

    display: str
    system: str
    unit: str
    aliases: list[str] = Field(min_length=1)
    conversions: dict[str, float] = Field(default_factory=dict)
    conventional: dict[str, Any]
    functional: dict[str, Any]
    direction: Direction
    athlete_note: str = ""
    confounders: list[Confounder] = Field(default_factory=list)
    sources: list[str] = Field(min_length=1)


class MarkerSpec(BaseModel):
    """One marker, resolved for the athlete's sex. What normalize, evaluate and the tools see."""

    key: str
    display: str
    system: str
    unit: str
    aliases: list[str]
    conversions: dict[str, float]
    conventional: Range
    functional: Range
    direction: Direction
    athlete_note: str
    confounders: list[Confounder]
    sources: list[str]


_PAREN = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")


def normalize_alias(name: str) -> str:
    """Lowercase, drop parenthesized qualifiers, turn punctuation into spaces, collapse spaces."""
    s = _PAREN.sub(" ", name.lower())
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def _resolve_range(block: dict[str, Any], sex: Sex, marker: str, field: str) -> Range:
    keys = set(block)
    if keys <= {"low", "high"}:
        chosen = block
    elif "male" in keys or "female" in keys:
        if sex not in block:
            raise RegistryError(f"{marker}.{field}: no '{sex}' block")
        chosen = block[sex]
        if not isinstance(chosen, dict) or not set(chosen) <= {"low", "high"}:
            raise RegistryError(f"{marker}.{field}.{sex}: expected {{low, high}}")
    else:
        raise RegistryError(f"{marker}.{field}: expected {{low, high}} or {{male, female}}")
    try:
        r = Range.model_validate(chosen)
    except ValidationError as exc:
        raise RegistryError(f"{marker}.{field}: {exc.errors()[0]['msg']}") from exc
    if r.low is None and r.high is None:
        raise RegistryError(f"{marker}.{field}: needs at least one of low, high")
    if r.low is not None and r.high is not None and r.low >= r.high:
        raise RegistryError(f"{marker}.{field}: low must be below high")
    return r


def _resolve(key: str, raw: dict[str, Any], sex: Sex) -> MarkerSpec:
    try:
        entry = RawMarkerEntry.model_validate(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        loc = ".".join(str(p) for p in e["loc"]) or "entry"
        raise RegistryError(f"{key}.{loc}: {e['msg']}") from exc
    if entry.system not in SYSTEMS:
        raise RegistryError(f"{key}.system: '{entry.system}' is not one of {sorted(SYSTEMS)}")
    conventional = _resolve_range(entry.conventional, sex, key, "conventional")
    functional = _resolve_range(entry.functional, sex, key, "functional")
    if (
        conventional.low is not None
        and functional.low is not None
        and functional.low < conventional.low
    ):
        raise RegistryError(f"{key}.functional: low {functional.low} below conventional low")
    if (
        conventional.high is not None
        and functional.high is not None
        and functional.high > conventional.high
    ):
        raise RegistryError(f"{key}.functional: high {functional.high} above conventional high")
    for unit, factor in entry.conversions.items():
        if factor <= 0:
            raise RegistryError(f"{key}.conversions: factor for '{unit}' must be positive")
        if unit == entry.unit and factor != 1.0:
            raise RegistryError(
                f"{key}.conversions: '{unit}' is the canonical unit; its factor must be 1.0"
            )
    return MarkerSpec(
        key=key,
        display=entry.display,
        system=entry.system,
        unit=entry.unit,
        aliases=entry.aliases,
        conversions=entry.conversions,
        conventional=conventional,
        functional=functional,
        direction=entry.direction,
        athlete_note=entry.athlete_note.strip(),
        confounders=entry.confounders,
        sources=entry.sources,
    )


class MarkerRegistry:
    def __init__(self, version: str, sex: Sex, markers: dict[str, MarkerSpec]) -> None:
        self.version = version
        self.sex = sex
        self.markers = markers
        self._alias_index: dict[str, str] = {}
        for key, spec in markers.items():
            for alias in spec.aliases:
                norm = normalize_alias(alias)
                if not norm:
                    raise RegistryError(f"{key}.aliases: '{alias}' normalizes to nothing")
                owner = self._alias_index.get(norm)
                if owner is not None and owner != key:
                    raise RegistryError(f"{key}.aliases: '{alias}' already belongs to '{owner}'")
                self._alias_index[norm] = key

    def get(self, key: str) -> MarkerSpec:
        return self.markers[key]

    def lookup(self, raw_name: str) -> MarkerSpec | None:
        key = self._alias_index.get(normalize_alias(raw_name))
        return self.markers[key] if key else None

    def __len__(self) -> int:
        return len(self.markers)

    def __iter__(self) -> Iterator[str]:
        return iter(self.markers)


def load_registry(sex: Sex, path: Path = MARKERS_PATH) -> MarkerRegistry:
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "version" not in doc or "markers" not in doc:
        raise RegistryError(f"{path.name}: top level needs 'version' and 'markers'")
    markers_raw = doc["markers"]
    if not isinstance(markers_raw, dict) or not markers_raw:
        raise RegistryError(f"{path.name}: 'markers' must be a non-empty mapping")
    markers = {str(k): _resolve(str(k), v, sex) for k, v in markers_raw.items()}
    return MarkerRegistry(str(doc["version"]), sex, markers)
