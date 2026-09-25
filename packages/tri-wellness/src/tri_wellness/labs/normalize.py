"""Raw lab rows to canonical results: alias mapping, unit conversion, bound handling. Pure."""

from __future__ import annotations

import re

from tri_wellness.labs.models import Bound, LabResult, NormalizeResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

# Longest prefixes first so '<=' is not read as '<'.
_BOUNDS: dict[str, Bound] = {"<=": "<=", ">=": ">=", "≤": "<=", "≥": ">=", "<": "<", ">": ">"}
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")  # e.g. '1,234.5'; '5,2' does not match


def _split_bound(text: str) -> tuple[str | None, str]:
    s = text.strip()
    prefix = next((p for p in _BOUNDS if s.startswith(p)), None)
    return prefix, (s[len(prefix) :].strip() if prefix else s)


def parse_value(text: str) -> tuple[float, Bound | None] | None:
    """'42' -> (42.0, None); '<5' -> (5.0, "<"); '≥ 60' -> (60.0, ">="); '1,234.5' ->
    (1234.5, None); 'Not detected', '5,2' (an ambiguous comma) and '-5' (no marker is negative)
    -> None."""
    prefix, body = _split_bound(text)
    if _THOUSANDS.match(body):
        body = body.replace(",", "")
    if body.startswith("-") or not _NUMBER.match(body):
        return None
    return float(body), (_BOUNDS[prefix] if prefix else None)


def bound_step(raw_value: str, value: float) -> float:
    """One unit in the last printed decimal place of a bounded raw value, scaled to the canonical
    unit of `value`: '<1.0' -> 0.1, '>60' -> 1, '<0.5' converted x10 -> 1.0. The open end of the
    bound's interval sits one step inside it. 0 when the text does not parse."""
    parsed = parse_value(raw_value)
    if parsed is None or parsed[0] == 0:
        return 0.0
    _, body = _split_bound(raw_value)
    decimals = len(body.partition(".")[2])
    return 10.0**-decimals * value / parsed[0]


def _unit_key(unit: str) -> str:
    return unit.strip().lower().replace(" ", "")


DIMENSIONLESS_UNITS: frozenset[str] = frozenset({"ratio", "%", "index", "score"})


def _factor(spec: MarkerSpec, unit: str | None) -> float | None:
    """1.0 for the canonical unit, the table's factor for a known printed unit, None otherwise.
    A dimensionless marker printed without a unit is in its canonical unit."""
    if unit is None or not unit.strip():
        return 1.0 if spec.unit in DIMENSIONLESS_UNITS else None
    table = {_unit_key(spec.unit): 1.0}
    for u, f in spec.conversions.items():
        table.setdefault(_unit_key(u), f)
    return table.get(_unit_key(unit))


def _ref(text: str | None, factor: float) -> float | None:
    """A printed reference bound in the canonical unit: converted by the same factor as
    the value."""
    if text is None:
        return None
    parsed = parse_value(text)
    return round(parsed[0] * factor, 4) if parsed else None


def normalize(raw_results: list[RawResult], registry: MarkerRegistry) -> NormalizeResult:
    out = NormalizeResult()
    taken: set[str] = set()
    for raw in raw_results:
        spec = registry.lookup(raw.name)
        if spec is None:
            out.unmapped.append(Unmapped(raw=raw, reason="name"))
            continue
        if spec.key in taken:
            out.unmapped.append(Unmapped(raw=raw, reason="duplicate", marker=spec.key))
            continue
        parsed = parse_value(raw.value)
        if parsed is None:
            out.unmapped.append(Unmapped(raw=raw, reason="value", marker=spec.key))
            continue
        factor = _factor(spec, raw.unit)
        if factor is None:
            out.unmapped.append(Unmapped(raw=raw, reason="unit", marker=spec.key))
            continue
        number, bound = parsed
        note: str | None = None
        if factor != 1.0:
            unit = raw.unit
            assert unit is not None  # a factor other than 1.0 comes only from a printed unit
            note = f"converted from {raw.value.strip()} {unit.strip()}"
        taken.add(spec.key)
        out.results.append(
            LabResult(
                marker=spec.key,
                value=round(number * factor, 4),
                unit=spec.unit,
                raw=raw,
                bound=bound,
                lab_ref_low=_ref(raw.ref_low, factor),
                lab_ref_high=_ref(raw.ref_high, factor),
                note=note,
            )
        )
    return out
