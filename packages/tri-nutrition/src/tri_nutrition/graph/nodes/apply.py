"""Apply node: the only place Garmin and TrainingPeaks are written. One call per change,
recorded as it goes. `write_change` is shared with the `today` command; `apply_changes` is the
batch the node and the coach both call."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from tri_core.db.repo import Conn
from tri_core.db.writes import SentUnrecorded, mark_failed, recorded_write
from tri_core.mcp.client import McpToolError
from tri_core.sync import ToolCaller
from tri_nutrition import repo
from tri_nutrition import store as S
from tri_nutrition.graph.deps import GraphDeps
from tri_nutrition.graph.nodes.targets import apply_overrides
from tri_nutrition.graph.state import NutritionState
from tri_nutrition.nutrition.garmin_calls import to_garmin_call
from tri_nutrition.nutrition.models import NutritionChange
from tri_nutrition.nutrition.tp_calls import result_note_id, to_tp_call
from tri_nutrition.tools.garmin import trim_settings

GARMIN_OPS = ("set_day_targets",)
TP_OPS = ("set_session_note", "set_race_note")
PENDING_AMBIGUOUS = "more than one matching note on TrainingPeaks; not claimed"


def _label(c: NutritionChange) -> str:
    return f"{c.op} {c.target_key or c.day}"


async def _check_ownership(deps: GraphDeps, change: NutritionChange) -> None:
    """Raise PermissionError when the change would overwrite something we did not write."""
    assert deps.tp is not None
    if change.op == "set_session_note":
        wid = str(change.payload["workout_id"])
        with deps.connect() as conn:
            if repo.session_note_owned(conn, wid):
                return
        current = await deps.tp.call_json("tp_get_workout_note", {"workout_id": wid})
        existing = current.get("note") if isinstance(current, dict) else None
        if existing and str(existing).strip():
            raise PermissionError(f"workout {wid} has a private note that is not agent-authored")
    elif change.op == "set_race_note" and change.target_key:
        with deps.connect() as conn:
            owned = repo.owned_note_ids(conn)
        if change.target_key not in owned:
            raise PermissionError(f"calendar note {change.target_key} is not agent-authored")


def _as_payload(result: Any) -> dict[str, Any]:
    return result if isinstance(result, dict) else {"result": result}


def _mark_written(conn: Conn, change: NutritionChange, note_id: str | None) -> None:
    if change.op in GARMIN_OPS:
        repo.mark_targets_written(conn, [change.day])
    elif change.op == "set_session_note":
        wid = str(change.payload["workout_id"])
        repo.mark_fuel_written_for(conn, "session", change.day, wid, None)
    else:
        repo.mark_fuel_written_for(conn, "race", change.day, None, note_id)


async def _record_and_send(
    deps: GraphDeps,
    server: ToolCaller,
    thread_id: str,
    change: NutritionChange,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """One server call inside its `nutrition_changes` row: pending before, applied after."""

    def mark_applied(conn: Conn, row_id: int, result: Any) -> None:
        note_id = result_note_id(change, result)
        repo.mark_change_applied(conn, row_id, _as_payload(result), target_key=note_id)
        _mark_written(conn, change, note_id)

    sent = False

    async def send() -> Any:
        nonlocal sent
        result = await server.call_json(name, args)
        sent = True
        return result

    try:
        rec = await recorded_write(
            deps.connect,
            table="nutrition_changes",
            insert_pending=lambda conn: repo.insert_pending_change(conn, thread_id, change),
            call=send,
            mark_applied=mark_applied,
        )
    except psycopg.Error as exc:
        if sent:
            raise SentUnrecorded(exc) from exc
        raise
    return _as_payload(rec.result)


async def write_change(deps: GraphDeps, thread_id: str, change: NutritionChange) -> dict[str, Any]:
    """Send one change to its server with its audit row recorded first, and mark the target
    written. Raises McpToolError/ValueError on failure, SentUnrecorded when the call went through
    but its row stayed pending, and PermissionError on an ownership refusal; neither refusal
    leaves a row."""
    if change.op in GARMIN_OPS:
        if deps.garmin is None:
            raise McpToolError("set_nutrition_daily_settings", "Garmin server unavailable")
        if change.day != deps.today():
            raise ValueError(f"Garmin can only hold today's target; {change.day} is not today")
        name, args = to_garmin_call(change)
        return await _record_and_send(deps, deps.garmin, thread_id, change, name, args)
    if change.op in TP_OPS:
        if deps.tp is None:
            raise McpToolError(change.op, "TrainingPeaks server unavailable")
        await _check_ownership(deps, change)
        name, args = to_tp_call(change)
        return await _record_and_send(deps, deps.tp, thread_id, change, name, args)
    raise ValueError(f"unknown operation {change.op}")


def _grams(v: Any) -> int | None:
    return int(round(float(v))) if v is not None else None


Verdict = Literal["applied", "missing", "ambiguous"]


def _verdict(found: bool) -> Verdict:
    return "applied" if found else "missing"


async def _verify(
    server: ToolCaller, change: NutritionChange, owned: set[str]
) -> tuple[Verdict, str | None]:
    """Whether a pending change is on its server, and the note id it concerns. A race-note
    create claims only a note no applied row owns, and only when exactly one matches."""
    p = change.payload
    if change.op == "set_day_targets":
        s = trim_settings(
            await server.call_json("get_nutrition_daily_settings", {"date": change.day.isoformat()})
        )
        got = (_grams(s["carbs_g"]), _grams(s["protein_g"]), _grams(s["fat_g"]))
        want = (_grams(p["carbs_grams"]), _grams(p["protein_grams"]), _grams(p["fat_grams"]))
        return _verdict(got == want), None
    if change.op == "set_session_note":
        cur = await server.call_json("tp_get_workout_note", {"workout_id": str(p["workout_id"])})
        note = cur.get("note") if isinstance(cur, dict) else None
        return _verdict(str(note or "").strip() == str(p["note"]).strip()), None
    if change.op == "set_race_note" and change.target_key:
        cur = await server.call_json("tp_get_note", {"note_id": change.target_key})
        note = cur.get("note") if isinstance(cur, dict) else None
        same = (
            isinstance(note, dict)
            and note.get("title") == p["title"]
            and note.get("description") == p["description"]
        )
        return _verdict(same), change.target_key
    if change.op == "set_race_note":
        day = str(p["date"])
        listed = await server.call_json("tp_list_notes", {"start_date": day, "end_date": day})
        notes = listed.get("notes") if isinstance(listed, dict) else None
        hits = [
            str(n["id"])
            for n in (notes if isinstance(notes, list) else [])
            if isinstance(n, dict)
            and n.get("title") == p["title"]
            and n.get("id") is not None
            and str(n["id"]) not in owned
        ]
        if len(hits) > 1:
            return "ambiguous", None
        if hits:
            return "applied", hits[0]
        return "missing", None
    return "missing", None


def _unchecked(row_id: int, exc: Exception) -> str:
    first = str(exc).splitlines()[0] if str(exc) else ""
    return f"row {row_id}: could not be checked ({type(exc).__name__}: {first}); left pending"


async def reconcile_pending(deps: GraphDeps) -> list[str]:
    """Settle `nutrition_changes` rows an earlier apply left `pending`: `applied` when the
    server shows the change, else `failed`. Returns one report line per row settled or left."""
    with deps.connect() as conn:
        rows = repo.pending_changes(conn)
        owned = repo.owned_note_ids(conn)
    lines: list[str] = []
    for row in rows:
        try:
            change = NutritionChange.model_validate(row["payload"])
        except Exception as exc:  # noqa: BLE001 - one bad row stays pending; the apply goes on
            lines.append(_unchecked(row["id"], exc))
            continue
        garmin = change.op in GARMIN_OPS
        server = deps.garmin if garmin else deps.tp
        name = "Garmin" if garmin else "TrainingPeaks"
        if server is None:
            lines.append(f"{_label(change)}: {name} unavailable; left pending")
            continue
        try:
            verdict, note_id = await _verify(server, change, owned)
        except McpToolError as exc:
            lines.append(f"{_label(change)}: {name} unreachable ({exc}); left pending")
            continue
        except Exception as exc:  # noqa: BLE001 - one bad row stays pending; the apply goes on
            lines.append(_unchecked(row["id"], exc))
            continue
        with deps.connect() as conn:
            if verdict == "applied":
                repo.mark_change_applied(conn, row["id"], {"reconciled": True}, target_key=note_id)
                _mark_written(conn, change, note_id)
                if change.op == "set_race_note" and note_id is not None:
                    owned.add(note_id)
                lines.append(f"{_label(change)}: found on {name}; recorded as applied")
            else:
                err = (
                    PENDING_AMBIGUOUS
                    if verdict == "ambiguous"
                    else f"not found on {name} after a pending write"
                )
                mark_failed(conn, "nutrition_changes", row["id"], err)
                lines.append(f"{_label(change)}: {err}; marked failed")
            conn.commit()
    return lines


def _server_down(deps: GraphDeps, change: NutritionChange) -> bool:
    return (change.op in GARMIN_OPS and deps.garmin is None) or (
        change.op in TP_OPS and deps.tp is None
    )


@dataclass
class ApplyResult:
    applied: list[NutritionChange]
    skipped: list[str]
    remaining: list[NutritionChange]
    held: list[NutritionChange]  # a subset of remaining: the server for these was down
    error: str | None
    profile_updated: bool
    reconciled: list[str] = field(default_factory=list)  # pending rows settled before the batch

    def report(self, total: int, overrides: dict[str, Any] | None) -> str:
        n_garmin = sum(1 for c in self.applied if c.op in GARMIN_OPS)
        n_tp = sum(1 for c in self.applied if c.op in TP_OPS)
        lines = [
            f"Applied {len(self.applied)} of {total} changes "
            f"(Garmin {n_garmin}, TrainingPeaks {n_tp})."
        ]
        lines += [f"  reconciled: {s}" for s in self.reconciled]
        lines += [f"  skipped: {s}" for s in self.skipped]
        if self.profile_updated:
            lines.append(f"  profile updated: {overrides}")
        if self.error:
            lines.append(f"  stopped: {self.error}")
            lines.append(
                f"  {len(self.remaining)} change(s) still pending; they will be re-proposed next "
                "turn."
            )
        return "\n".join(lines)


async def apply_changes(
    deps: GraphDeps,
    store: BaseStore,
    changes: Sequence[NutritionChange],
    thread_id: str,
    *,
    overrides: dict[str, Any] | None,
) -> ApplyResult:
    """Send each change to its server in order, recording every attempt in `nutrition_changes`
    under `thread_id` (pending, then applied or failed); pending rows from earlier applies are
    reconciled first. Changes whose server is down are held (kept in `remaining`); an ownership
    refusal drops the change; a server error, or a change sent but not recorded (it leaves
    `remaining` and is reconciled next apply), stops the batch. `overrides` are written to the
    profile in the Store only when every change went through."""
    reconciled = await reconcile_pending(deps)
    todo = list(changes)
    applied: list[NutritionChange] = []
    skipped: list[str] = []
    held: list[NutritionChange] = []
    remaining = list(todo)
    error: str | None = None
    for change in todo:
        if _server_down(deps, change):
            held.append(change)
            continue
        try:
            await write_change(deps, thread_id, change)
        except PermissionError as exc:
            skipped.append(f"{_label(change)}: {exc}; dropped")
            remaining.remove(change)
            continue
        except SentUnrecorded as exc:  # the database is unhealthy: stop, but never re-send it
            error = f"{_label(change)}: {exc}"
            remaining.remove(change)
            break
        except (McpToolError, ValueError) as exc:
            error = f"{_label(change)} failed: {exc}"
            break
        applied.append(change)
        remaining.remove(change)
    if error is None:
        remaining = [c for c in remaining if c in held]
    if held:
        servers = sorted({"Garmin" if c.op in GARMIN_OPS else "TrainingPeaks" for c in held})
        held_msg = (
            f"{' and '.join(servers)} server unavailable; {len(held)} change(s) held pending."
        )
        error = held_msg if error is None else f"{error}; {held_msg}"

    persisted = False
    if error is None and not remaining and overrides:
        base = await S.get_profile(store)
        if base is not None:
            await S.put_profile(store, apply_overrides(base, overrides))
            persisted = True
    return ApplyResult(
        applied=applied,
        skipped=skipped,
        remaining=remaining,
        held=held,
        error=error,
        profile_updated=persisted,
        reconciled=reconciled,
    )


def make_apply_node(deps: GraphDeps) -> Any:
    async def apply(
        state: NutritionState, config: RunnableConfig, *, store: BaseStore
    ) -> dict[str, Any]:
        changes = list(state.get("pending_changes") or [])
        overrides = state.get("profile_overrides")
        r = await apply_changes(
            deps, store, changes, str(config["configurable"]["thread_id"]), overrides=overrides
        )
        clean = r.error is None and not r.remaining
        return {
            "pending_changes": r.remaining,
            "pending_violations": (state.get("pending_violations") or {}) if r.remaining else {},
            "pending_summary": state.get("pending_summary") if r.remaining else None,
            "last_error": r.error,
            "review_decision": None,
            "profile_overrides": None if clean else overrides,
            "messages": [AIMessage(r.report(len(changes), overrides))],
        }

    return apply
