"""Raw lab rows to canonical results: alias mapping, unit conversion, bound handling. Pure."""

from __future__ import annotations

import re

from tri_wellness.labs.models import LabResult, NormalizeResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MarkerRegistry, MarkerSpec

_BOUND_PREFIXES = ("<=", ">=", "≤", "≥", "<", ">")
_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


def _fmt(n: float) -> str:
    return str(int(n)) if n == int(n) else str(n)


def parse_value(text: str) -> tuple[float, str | None] | None:
    """'42' -> (42.0, None); '<5' -> (5.0, note); 'Not detected' -> None."""
    s = text.strip()
    prefix = next((p for p in _BOUND_PREFIXES if s.startswith(p)), None)
    body = s[len(prefix) :].strip() if prefix else s
    body = body.replace(",", "")
    if not _NUMBER.match(body):
        return None
    n = float(body)
    note = f"value '{s}' stored as bound {_fmt(n)}" if prefix else None
    return n, note


def _unit_key(unit: str) -> str:
    return unit.strip().lower().replace(" ", "")


def _factor(spec: MarkerSpec, unit: str | None) -> float | None:
    if unit is None:
        return None
    table = {_unit_key(spec.unit): 1.0}
    for u, f in spec.conversions.items():
        table.setdefault(_unit_key(u), f)
    return table.get(_unit_key(unit))


def _ref(text: str | None) -> float | None:
    if text is None:
        return None
    parsed = parse_value(text)
    return parsed[0] if parsed else None


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
        number, note = parsed
        notes = [note] if note else []
        if factor != 1.0:
            notes.append(f"converted from {raw.value.strip()} {raw.unit}")
        taken.add(spec.key)
        out.results.append(
            LabResult(
                marker=spec.key,
                value=round(number * factor, 4),
                unit=spec.unit,
                raw=raw,
                lab_ref_low=_ref(raw.ref_low),
                lab_ref_high=_ref(raw.ref_high),
                note="; ".join(notes) or None,
            )
        )
    return out
