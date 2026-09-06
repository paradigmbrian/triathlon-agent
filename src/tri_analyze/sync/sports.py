"""Map source-specific sport labels onto one small vocabulary."""

SPORTS = ("swim", "bike", "run", "brick", "strength", "race", "rest", "other")

_TP = {
    "swim": "swim",
    "bike": "bike",
    "mtnbike": "bike",
    "run": "run",
    "brick": "brick",
    "strength": "strength",
    "race": "race",
    "dayoff": "rest",
}


def normalize_tp_sport(label: str | None) -> str:
    if not label:
        return "other"
    return _TP.get(label.strip().lower(), "other")


def normalize_garmin_sport(type_key: str | None) -> str:
    if not type_key:
        return "other"
    k = type_key.lower()
    if "swim" in k:
        return "swim"
    if any(t in k for t in ("cycling", "biking", "ride", "bike")):
        return "bike"
    if "running" in k or k == "run":
        return "run"
    if "strength" in k:
        return "strength"
    if k in ("multi_sport", "triathlon", "duathlon"):
        return "brick"
    return "other"
