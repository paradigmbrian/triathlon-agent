# Guardrails 02: Consult Budget, One Held-Review Rule, Private Sub-graphs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The coach cannot consult a sub-agent past its per-turn budget, every host answers "a review is waiting" with one shared definition, and the embedded planning and nutrition graphs stop writing checkpoints into the coach's thread.

**Architecture:** `paused_review(snap)` moves into `tri_core.harness.turns` and every host imports it; the planning and nutrition chat loops open a waiting review before reading a message; the nutrition check-in refuses any thread that is not idle, as planning's already does. tri-coach compiles the embedded graphs with `checkpointer=False`. `CoachState.consults` counts consultations per domain; the coach node closes the counts into `make_handoff_tools(max_consults, spent)` and the context block, and a consult past the budget returns a budget `ToolMessage` instead of handing off. The coach's proposal lines name refused items as "not proposed".

**Tech Stack:** Python 3.12, LangGraph 1.2.11, langchain-core 1.6.2, `langchain.agents.create_agent`, Pydantic v2, pytest, FastAPI (tri-web, untouched except imports).

**Spec:** `docs/superpowers/specs/2026-09-24-guardrails-design.md` (sections 5, 6, 7, the Plan 02 half of 9 and 11). Plan 01 (`docs/superpowers/plans/2026-09-27-guardrails-01-tss-and-refuse.md`) is merged at `main` @ d9ca6b0.

**Branch:** `feat/guardrails-consults` off `main` @ d9ca6b0 (created with this plan).

## Global Constraints

- Budget message, exactly: `consult budget for <domain> is spent this turn (<n> of <n>); explain what you have and stop, or ask the athlete`, where `<n>` is `max_consults`.
- The budget is per domain (`planning`, `nutrition`) and per turn; `start_node` resets `consults` to `{}`. The nutrition regenerate brief (the follow-on after an apply) is not a consultation: it neither counts nor is blocked.
- `max_consults` comes from `CoachDeps.max_consults` (setting `TRI_COACH_MAX_CONSULTS_PER_DOMAIN`, default 2). `make_handoff_tools()` with no arguments stays unlimited (the eval target and the tool tests call it that way).
- Context line, exactly: `Consults left this turn: planning <p>, nutrition <n>.` It appears only when the coach node sets `CoachContext.consults_left`.
- Coach `PROMPT_VERSION` goes from `"3"` to `"4"` once, in Task 4 (the eval experiment becomes `coach-v4`). Task 5 edits `COACH_RULES` again under the same version.
- `paused_review(snap)` has one definition, in `tri_core/harness/turns.py`: the payload of the first interrupt of the first task when `snap.next == ("review",)`, else `None`.
- Embedded graphs are compiled with `checkpointer=False`; the `InMemorySaver` and `make_serde` imports leave `tri_coach/graph/graph.py`.
- Keyed violation lines read `<where> not proposed: <v joined by "; ">` (`week of <w>`, `session <id>`, `race note`). A no-change proposal that carries `pending_violations` is not a question; it renders as `<id> (<domain>) proposed no changes` plus its `violations:` line.
- **Brian's database rule:** the implementer runs no DDL or writes against `tri_analyze` or `tri_analyze_test` outside the test suite. No migration in this plan. The optional checkpoint cleanup in Task 6 is printed for Brian, never run.
- **Brian's dependency rule:** before the first edit touching LangGraph or langchain APIs (`compile(checkpointer=...)`, `ToolMessage` returned from a tool, `astream(subgraphs=True)`), look up the installed versions (`uv pip show langgraph langchain-core langchain`) in Context7. Nothing here needs an API the repo does not already use.
- Run `uv run ruff format` on the touched packages before each commit.

## Deviations from the spec (decided while planning, 2026-09-27)

1. **The consult counts are closed over, not injected.** The spec has `_consult` take `consults` through `InjectedState("consults")`. The coach's tools run inside a `create_agent` sub-agent (`tri_core.harness.agents.make_subagent`) whose state holds only its own messages, so `InjectedState("consults")` would never see `CoachState`. The coach node reads `state["consults"]` and builds the handoff tools with `make_handoff_tools(deps.max_consults, spent)` on every entry. That is exact: a consult unwinds the sub-agent at once and the coach node is re-entered after every consultation.
2. **Most of spec §6 already shipped with the correctness fixes.** tri-web `POST /api/coach/turns` returns 409 `{"reason": "paused"}` and keeps the review (`test_a_turn_during_a_paused_review_is_409_and_keeps_the_review`); the composer is disabled while paused (`web/src/components/chat/Chat.tsx`); all three check-ins refuse a review left by an earlier run. This plan adds the shared helper, the planning and nutrition chat loops, and the nutrition check-in's missing case (next item). No tri-web behaviour changes.
3. **`tri-nutrition check-in` refuses any thread that is not idle,** as `tri-planning check-in` does (`snap.next or pending_changes`). Today it refuses only `next == ("review",)`. A partial apply leaves its remainder in `pending_changes` with `next == ()`; the next `check-in --yes` routes straight to review (`route_start`) and approves a change set an earlier run produced, which spec §6 forbids.
4. **The coach check-in keeps refusing while a held `pending` set exists.** Spec §6 says a held set "is not a paused review ... so a new turn is allowed"; that applies to chat and the web (both already allow it). The check-in's refusal predates this spec and is documented in the coach README; changing unattended behaviour is out of scope.
5. **Plan 01's deviation 11 lands here:** the coach's keyed violation lines say "not proposed", and a consultation where every item was refused is not reported as "asked instead of proposing". Plan 01 left the lines as `week of <w>: …` to avoid touching the coach twice.
6. **`tri-wellness ingest` uses the shared helper too.** Its private `_pending_payload` plus `snap.next == ("review",)` is the same definition; spec §6 wants one.
7. **Checkpoints already written under `planning:<id>` and `nutrition:<id>` on thread `coach` stay.** Nothing reads them. Task 6 prints optional cleanup SQL for Brian.

### Existing tests this plan changes, and why

- `tri-coach/tests/test_prompt.py::test_prompt_order_is_rules_context_memory_and_names_the_limit`: `PROMPT_VERSION == "4"` and the budget sentence's new wording (Task 4). The rule text changes by design.
- `tri-coach/tests/test_nodes.py`: `test_a_consultation_carries_the_planning_violations_by_week` and `test_nutrition_proposals_carry_fuel_violations_by_session_and_race` pin the keyed wording (Task 5); `test_a_no_change_planning_proposal_keeps_its_refused_weeks` and `test_a_no_change_nutrition_proposal_keeps_its_refused_notes` flip `question` to `None` (Task 5). Each keeps every other assertion.

## Review Focus

- **A coach thread saved before this change, resumed after it** (a review answered with reject goes back to `coach` without passing `start`): the missing `consults` key reads as `{}`, the coach runs with a full budget, no `KeyError`. Test: `test_a_thread_without_consults_runs_with_a_full_budget` (Task 4).
- **The follow-on after an apply when nutrition's budget is spent:** the regenerate brief still runs and does not count. Test: `test_a_consultation_counts_against_its_domain_and_a_regeneration_does_not` (Task 4).
- **Planning's budget spent, nutrition's not:** `consult_nutrition` still hands off. Test: `test_the_budget_is_per_domain` (Task 4).
- **The REPL and tri-web still see the sub-agent's steps** once the embedded graphs have no checkpointer (`astream(subgraphs=True)` namespaces `planning:<id>`). Test: `test_a_consultation_streams_its_sub_graph_and_checkpoints_nothing` (Task 3).
- **A nutrition thread holding a partial apply's remainder, or stopped mid-run:** `check-in --yes` exits 3 without starting a turn, so it cannot approve what an earlier run proposed. Test: `test_checkin_run_never_starts_a_turn_on_a_thread_that_is_not_idle` (Task 2).

---

### Task 1: One `paused_review`, in the harness

**Files:**
- Modify: `packages/tri-core/src/tri_core/harness/turns.py` (add `paused_review`)
- Modify: `packages/tri-coach/src/tri_coach/repl.py` (delete its `paused_review`, import the harness one)
- Modify: `packages/tri-coach/src/tri_coach/checkin.py`, `packages/tri-web/src/tri_web/routes/coach.py`, `packages/tri-web/src/tri_web/thread.py`, `packages/tri-web/src/tri_web/today.py` (imports)
- Modify: `packages/tri-wellness/src/tri_wellness/repl.py` (`run_ingest`; delete `_pending_payload`)
- Modify: `packages/tri-core/README.md` (the `harness.turns` row)
- Test: `packages/tri-core/tests/test_harness_turns.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `tri_core.harness.turns.paused_review(snap: Any) -> dict[str, Any] | None`. Task 2 imports it into the planning and nutrition REPLs.

- [ ] **Step 1: Write the failing test**

In `packages/tri-core/tests/test_harness_turns.py`, add `from types import SimpleNamespace` to the imports and `paused_review` to the `tri_core.harness.turns` import list, then append:

```python
def test_paused_review_reads_only_a_review_that_is_waiting():
    payload = {"narration": "n", "proposals": []}
    waiting = SimpleNamespace(interrupts=(Interrupt(value=payload),))
    assert paused_review(SimpleNamespace(next=("review",), tasks=(waiting,))) == payload
    # stopped at review before its interrupt ran: nothing to answer
    stopped = SimpleNamespace(interrupts=())
    assert paused_review(SimpleNamespace(next=("review",), tasks=(stopped,))) is None
    assert paused_review(SimpleNamespace(next=("apply",), tasks=(waiting,))) is None
    assert paused_review(SimpleNamespace(next=(), tasks=())) is None
    assert paused_review(SimpleNamespace(next=("review",))) is None  # a stub without tasks
    assert paused_review(None) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest packages/tri-core/tests/test_harness_turns.py -v -k paused`
Expected: collection error, `ImportError: cannot import name 'paused_review' from 'tri_core.harness.turns'`.

- [ ] **Step 3: Add `paused_review` to the harness**

In `packages/tri-core/src/tri_core/harness/turns.py`, below `turn_config`:

```python
def paused_review(snap: Any) -> dict[str, Any] | None:
    """The interrupt payload of a review that is still waiting, from a state snapshot: the
    thread's next node is `review` and its first task holds an interrupt. The one definition
    every host uses to decide that a new turn must wait."""
    if snap is None or getattr(snap, "next", ()) != ("review",):
        return None
    tasks = getattr(snap, "tasks", ()) or ()
    if tasks and tasks[0].interrupts:
        return dict(tasks[0].interrupts[0].value)
    return None
```

- [ ] **Step 4: Point every host at it**

- `packages/tri-coach/src/tri_coach/repl.py`: delete the `paused_review` function and change the turns import to `from tri_core.harness.turns import format_failure, paused_review, stream_turn, turn_config`.
- `packages/tri-coach/src/tri_coach/checkin.py`: change `from tri_coach.repl import Out, paused_review, render_review, run_turn` to `from tri_coach.repl import Out, render_review, run_turn` and add `from tri_core.harness.turns import paused_review`.
- `packages/tri-web/src/tri_web/routes/coach.py`, `thread.py`, `today.py`: replace `from tri_coach.repl import paused_review` with `from tri_core.harness.turns import paused_review` (keep the import block sorted; `uv run ruff check --fix` sorts it).
- `packages/tri-wellness/src/tri_wellness/repl.py`: add `paused_review` to the `from tri_core.harness.turns import run_agent_turn, stream_turn, turn_config` line, delete `_pending_payload`, and in `run_ingest` replace

```python
    if snap.next == ("review",) and (pending := _pending_payload(snap)) is not None:
```

with

```python
    if (pending := paused_review(snap)) is not None:
```

Then run `git grep -n "_pending_payload\|tri_coach.repl import.*paused_review\|def paused_review" -- packages`. Expected: only `packages/tri-core/src/tri_core/harness/turns.py: def paused_review`.

- [ ] **Step 5: README row**

In `packages/tri-core/README.md`, the `harness.turns` row becomes:

```
| `harness.turns` | `stream_turn`, `AgentTurnPrinter`, `GraphTurnPrinter`, `run_agent_turn`, `run_graph_turn`, `api_error_message`, `turn_config`, `paused_review` (the one test for "a review is waiting") |
```

- [ ] **Step 6: Run the affected suites**

Run: `uv run pytest packages/tri-core packages/tri-coach packages/tri-web packages/tri-wellness -q`
Expected: all pass (no behaviour changed).

- [ ] **Step 7: Commit**

```bash
uv run ruff format packages/tri-core packages/tri-coach packages/tri-web packages/tri-wellness
git add packages/tri-core packages/tri-coach packages/tri-web packages/tri-wellness
git commit -m "refactor(core): paused_review lives in harness.turns; every host imports it"
```

---

### Task 2: Planning and nutrition chat open a waiting review; nutrition check-in refuses a busy thread

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/repl.py` (`chat_loop`)
- Modify: `packages/tri-nutrition/src/tri_nutrition/repl.py` (`chat_loop`, `checkin_run`)
- Test: `packages/tri-planning/tests/test_repl.py`, `packages/tri-nutrition/tests/test_repl.py`

**Interfaces:**
- Consumes: `tri_core.harness.turns.paused_review` (Task 1).
- Produces: `chat_loop` (both packages) enters the review dialogue before reading a message when the thread is paused at review; `/pending` shows the waiting review's own payload (with its violations) when there is one. `tri_nutrition.repl.checkin_run` returns 3 without starting a turn whenever the thread is not idle.

- [ ] **Step 1: Write the failing tests**

`packages/tri-planning/tests/test_repl.py`: add `from types import SimpleNamespace`, then append:

```python
class PausedGraph(StubGraph):
    """A thread the athlete left at review: the first state read is the waiting review."""

    def __init__(self, turns, payload):
        super().__init__(turns)
        self.payload = payload
        self.reads = 0

    async def aget_state(self, config):
        self.reads += 1
        if self.reads == 1:
            waiting = SimpleNamespace(interrupts=(Interrupt(value=self.payload),))
            return SimpleNamespace(next=("review",), values={}, tasks=(waiting,))
        return await super().aget_state(config)


def waiting_payload():
    return interrupt_event([change()])[2]["__interrupt__"][0].value


async def test_chat_loop_opens_a_waiting_review_before_reading_a_message():
    done_ev = ((), "updates", {"apply": {"messages": [AIMessage(content="applied 1 of 1")]}})
    graph = PausedGraph([[done_ev]], waiting_payload())
    inputs = iter(["approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    assert "Ride" in "".join(buf)
    # "approve" answered the review; it was never sent as a new message
    assert len(graph.inputs) == 1 and isinstance(graph.inputs[0], Command)
    assert graph.inputs[0].resume == {"action": "approve"}


async def test_quitting_at_a_waiting_review_leaves_it_waiting():
    graph = PausedGraph([], waiting_payload())
    inputs = iter(["/quit"])

    async def read():
        return next(inputs, None)

    await chat_loop(graph, read=read, out=lambda s: None)
    assert graph.inputs == []
```

`packages/tri-nutrition/tests/test_repl.py` (it already imports `SimpleNamespace`, `Interrupt`, `Command`, `AIMessage`, `chat_loop` and `checkin_run`): append the same two chat-loop tests with nutrition's helpers, plus the check-in test:

```python
class PausedGraph(StubGraph):
    """A thread the athlete left at review: the first state read is the waiting review."""

    def __init__(self, turns, payload):
        super().__init__(turns)
        self.payload = payload
        self.reads = 0

    async def aget_state(self, config):
        self.reads += 1
        if self.reads == 1:
            waiting = SimpleNamespace(interrupts=(Interrupt(value=self.payload),))
            return SimpleNamespace(next=("review",), values={}, tasks=(waiting,))
        return await super().aget_state(config)


def waiting_payload():
    return interrupt_event([change()])[2]["__interrupt__"][0].value


async def test_chat_loop_opens_a_waiting_review_before_reading_a_message():
    done = ((), "updates", {"apply": {"messages": [AIMessage(content="Garmin: applied 1 of 1")]}})
    graph = PausedGraph([[done]], waiting_payload())
    inputs = iter(["approve", "/quit"])

    async def read():
        return next(inputs, None)

    buf = []
    await chat_loop(graph, read=read, out=buf.append)
    assert "approve / reject" in "".join(buf)
    assert len(graph.inputs) == 1 and isinstance(graph.inputs[0], Command)
    assert graph.inputs[0].resume == {"action": "approve"}


async def test_quitting_at_a_waiting_review_leaves_it_waiting():
    graph = PausedGraph([], waiting_payload())
    inputs = iter(["/quit"])

    async def read():
        return next(inputs, None)

    await chat_loop(graph, read=read, out=lambda s: None)
    assert graph.inputs == []


class _Busy:
    """A thread that is not idle: `state` is what aget_state returns; a turn must not start."""

    def __init__(self, state) -> None:
        self.state = state
        self.turned = False

    async def astream(self, payload, config=None, **kwargs):
        self.turned = True
        return
        yield

    async def aget_state(self, config):
        return self.state


async def test_checkin_run_never_starts_a_turn_on_a_thread_that_is_not_idle():
    # a partial apply's remainder: next is empty, the changes wait in state
    remainder = SimpleNamespace(next=(), values={"pending_changes": [change()]}, tasks=())
    graph = _Busy(remainder)
    printed: list[str] = []
    assert await checkin_run(graph, thread_id="n", out=printed.append, approve=True) == 3
    assert not graph.turned and "already waiting at review" in "".join(printed)
    # a run that stopped mid-graph
    graph = _Busy(SimpleNamespace(next=("fuel",), values={}, tasks=()))
    printed.clear()
    assert await checkin_run(graph, thread_id="n", out=printed.append, approve=True) == 3
    assert not graph.turned and "stopped mid-run at fuel" in "".join(printed)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-planning/tests/test_repl.py packages/tri-nutrition/tests/test_repl.py -v -k "waiting or idle"`
Expected: the chat-loop tests FAIL (`graph.inputs[0]` is `{"messages": [HumanMessage("approve")]}`; the quit test passes already and stays as the guard). The check-in test FAILS with `assert 1 == 3` or `0 == 3` and `graph.turned` true.

- [ ] **Step 3: Planning chat loop**

In `packages/tri-planning/src/tri_planning/repl.py`, add `paused_review` to the harness import (`from tri_core.harness.turns import GraphTurnPrinter, paused_review, run_graph_turn`). In `chat_loop`, replace `pending: dict[str, Any] | None = None` with:

```python
    # A review the athlete walked away from is still paused in the checkpoint: finish it first,
    # or the next typed message restarts the graph and the review is shown again without it.
    pending = paused_review(await graph.aget_state({"configurable": {"thread_id": thread_id}}))
```

and replace the `/pending` branch body with:

```python
            if name == "pending":
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
                changes = snap.values.get("pending_changes") or []
                paused = paused_review(snap)
                if paused is not None:
                    pending = paused
                elif not changes:
                    out("nothing pending\n")
                else:
                    pending = {
                        "summary": snap.values.get("pending_summary") or "",
                        "changes": [c.model_dump(mode="json") for c in changes],
                        "violations": snap.values.get("pending_violations") or {},
                        "last_error": snap.values.get("last_error"),
                    }
                continue
```

- [ ] **Step 4: Nutrition chat loop and check-in**

In `packages/tri-nutrition/src/tri_nutrition/repl.py`, add `paused_review` to `from tri_core.harness.turns import GraphTurnPrinter, run_graph_turn`. In `chat_loop`, make the same two edits as Step 3 (the nutrition `/pending` payload keeps its keys: `summary`, `changes`, `last_error`, plus `"violations": snap.values.get("pending_violations") or {}`).

In `checkin_run`, replace the block from `snap = await graph.aget_state(cfg)` through its `return 3` with:

```python
    snap = await graph.aget_state(cfg)
    values = snap.values or {}
    waiting = paused_review(snap)
    if waiting is None and values.get("pending_changes"):
        # a partial apply's remainder, or a run stopped before its interrupt
        waiting = {
            "summary": values.get("pending_summary") or "",
            "changes": [c.model_dump(mode="json") for c in values["pending_changes"]],
            "violations": values.get("pending_violations") or {},
            "last_error": values.get("last_error"),
        }
    if waiting is not None:
        out("a change set is already waiting at review:\n" + render_review(waiting) + "\n")
        out(ALREADY_PAUSED_HINT + "\n")
        return 3
    if snap.next:
        out(
            f"the nutrition thread stopped mid-run at {', '.join(snap.next)}; "
            "send any message in `tri-nutrition chat` to clear it\n"
        )
        return 3
```

Add to its docstring's exit 3: `, or the thread is not idle (a partial apply's remainder, a run stopped mid-graph)`.

- [ ] **Step 5: Run the planning and nutrition suites**

Run: `uv run pytest packages/tri-planning packages/tri-nutrition -q`
Expected: all pass. `tri-nutrition/tests/test_graph.py::test_checkin_run_pauses_and_a_later_yes_does_not_approve_it` still passes (a real waiting review; `paused_review` matches it).

- [ ] **Step 6: Commit**

```bash
uv run ruff format packages/tri-planning packages/tri-nutrition
git add packages/tri-planning packages/tri-nutrition
git commit -m "feat(planning,nutrition): chat opens a waiting review first; nutrition check-in refuses a busy thread"
```

---

### Task 3: Embedded graphs with no checkpointer

**Files:**
- Modify: `packages/tri-planning/src/tri_planning/graph/graph.py` (`build_graph` signature)
- Modify: `packages/tri-nutrition/src/tri_nutrition/graph/graph.py` (`build_graph` signature)
- Modify: `packages/tri-coach/src/tri_coach/graph/graph.py` (`build_graph`)
- Modify: `docs/architecture/harness.md`, `packages/tri-coach/README.md`
- Test: `packages/tri-coach/tests/test_graph.py`, `packages/tri-coach/tests/test_graph_apply.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `tri_planning.graph.graph.build_graph(deps, checkpointer: BaseCheckpointSaver[Any] | Literal[False], *, embedded=False)` and `tri_nutrition.graph.graph.build_graph(deps, checkpointer: BaseCheckpointSaver[Any] | Literal[False], store, *, embedded=False)`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-coach/tests/test_graph.py`, append:

```python
async def test_a_consultation_streams_its_sub_graph_and_checkpoints_nothing(
    nocommit, make_deps, mem_store
):
    seed_active_plan(nocommit)
    saver = InMemorySaver(serde=make_serde(STATE_TYPES))
    models = scripted(
        coach=[
            consult("planning", "Knee pain. Move w1 off Wednesday; hold weekly TSS."),
            AIMessage(content="Planning suggests moving Wednesday's tempo to Friday."),
        ],
        planning=[move_call(), AIMessage(content="Proposed a move.")],
        nutrition=[],
        analyst=[],
    )
    graph = build_graph(make_deps(tp=FakeTp(), **models), saver, mem_store)
    seen = set()
    async for ns, _mode, _data in graph.astream(
        {"messages": [HumanMessage("my knee hurts")]}, CFG, stream_mode=["updates"], subgraphs=True
    ):
        seen.add(ns[0].split(":")[0] if ns else "")
    assert "planning" in seen  # the REPL and tri-web still see the sub-agent's steps
    saved = {c.config["configurable"].get("checkpoint_ns", "") for c in saver.list(None)}
    assert saved == {""}  # nothing under planning:<task id>; the parent owns the messages
```

`packages/tri-coach/tests/test_graph_apply.py`, append:

```python
async def test_a_nutrition_consultation_checkpoints_nothing_on_the_coach_thread(
    ndb, make_deps, mem_store
):
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    saver = InMemorySaver(serde=make_serde(STATE_TYPES))
    scripts = {
        "coach": [
            consult("nutrition", "Race block starts Monday; raise activity_factor to 1.45."),
            AIMessage(content="Nutrition proposes a higher activity factor."),
        ],
        "planning": [],
        "nutrition": [
            tool_call(
                "propose_target_changes",
                {"overrides": {"activity_factor": 1.45}, "reason": "race block"},
            ),
            AIMessage(content="Proposed."),
        ],
        "analyst": [],
    }
    models = {k: ScriptedChatModel(script=v) for k, v in scripts.items()}
    deps = make_deps(garmin=FakeGarmin(), tp=NutritionFakeTp(), **models)
    graph = build_graph(deps, saver, mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("race block starts")]}, CFG)
    assert out["proposals"][0].domain == "nutrition"
    saved = {c.config["configurable"].get("checkpoint_ns", "") for c in saver.list(None)}
    assert saved == {""}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_graph.py packages/tri-coach/tests/test_graph_apply.py -v -k checkpoints`
Expected: FAIL on `saved == {""}`: the set also holds `planning:<id>` (and `nutrition:<id>`), because LangGraph takes the parent config's checkpointer over the private `InMemorySaver`. (Checked on langgraph 1.2.11 on 2026-09-27: a child compiled with its own saver and invoked with the parent's config wrote under `<node>:<task id>` in the parent's saver; one compiled with `checkpointer=False` wrote nothing.)

- [ ] **Step 3: Accept `False` in the sub-graph builders**

In both `graph.py` files add `Literal` to the `typing` import and change the parameter to `checkpointer: BaseCheckpointSaver[Any] | Literal[False]`. Add one line to each `build_graph` docstring: `Embedded, the caller passes checkpointer=False: the parent graph owns the messages and nothing the run does is saved.`

- [ ] **Step 4: Compile the embedded graphs without a checkpointer**

In `packages/tri-coach/src/tri_coach/graph/graph.py`, delete the `InMemorySaver`, `make_serde`, `NUTRITION_STATE_TYPES` and `PLANNING_STATE_TYPES` imports and replace the top of `build_graph`:

```python
def build_graph(deps: CoachDeps, checkpointer: BaseCheckpointSaver[Any], store: BaseStore) -> Any:
    # No checkpointer: a graph invoked inside a node would otherwise take the parent config's
    # checkpointer and save every step under thread "coach". The coach's state already carries
    # what a consultation returns, and each consultation starts fresh.
    planning_graph = build_planning_graph(deps.planning_deps, False, embedded=True)
    nutrition_graph = build_nutrition_graph(deps.nutrition_deps, False, store, embedded=True)
```

- [ ] **Step 5: Docs**

`docs/architecture/harness.md`, the `consult_planning` bullet under "How the coach graph routes" becomes:

```
- `consult_planning` and `consult_nutrition` run the embedded planning or nutrition graph with no checkpointer (`checkpointer=False`; the parent graph owns the messages, and each consultation starts fresh) and swap the result into the original tool message.
```

`packages/tri-coach/README.md`: in the mermaid block, `fresh InMemorySaver per run` becomes `no checkpointer`; the invariants sentence ending the paragraph becomes `...no `review` or `apply` node; consultations run with no checkpointer (compiled with `checkpointer=False`), so nothing a sub-graph does is saved and a consultation never sees an earlier one.`

- [ ] **Step 6: Run the coach and web suites**

Run: `uv run pytest packages/tri-coach packages/tri-web -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
uv run ruff format packages/tri-planning packages/tri-nutrition packages/tri-coach
git add packages/tri-planning packages/tri-nutrition packages/tri-coach docs/architecture/harness.md
git commit -m "fix(coach): embedded planning and nutrition graphs run with no checkpointer"
```

---

### Task 4: The consult budget

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/state.py` (`consults`)
- Modify: `packages/tri-coach/src/tri_coach/graph/graph.py` (`start_node`)
- Modify: `packages/tri-coach/src/tri_coach/tools/handoff.py` (`CONSULT_BUDGET_SPENT`, `_consult`, `make_handoff_tools`)
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/planning.py` (`counted`, the node update)
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py` (the consult path's update)
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/coach.py` (tools and context per entry)
- Modify: `packages/tri-coach/src/tri_coach/context.py` (`consults_left`, `_consults_line`)
- Modify: `packages/tri-coach/src/tri_coach/prompts/coach.py` (budget rule, `PROMPT_VERSION = "4"`)
- Test: `packages/tri-coach/tests/{test_tools,test_nodes,test_prompt,test_graph}.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `CoachState.consults: dict[str, int]` (domain to consultations this turn).
  - `tri_coach.tools.handoff.CONSULT_BUDGET_SPENT: str` (a `str.format` template with `domain` and `n`).
  - `make_handoff_tools(max_consults: int | None = None, spent: Mapping[str, int] | None = None) -> list[BaseTool]`.
  - `tri_coach.graph.nodes.planning.counted(state: CoachState, domain: Domain) -> dict[str, int]`.
  - `CoachContext.consults_left: dict[str, int] | None = None`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-coach/tests/test_tools.py`, append:

```python
BUDGET = (
    "consult budget for planning is spent this turn (2 of 2); explain what you have and stop, "
    "or ask the athlete"
)


async def test_a_consult_past_the_budget_returns_the_budget_message_and_no_handoff():
    model = ScriptedChatModel(
        script=[
            tool_call("consult_planning", {"instruction": "Drop w1; hold TSS."}),
            AIMessage(content="I have what I need."),
        ]
    )
    graph = outer_graph(model, make_handoff_tools(2, {"planning": 2}))
    out = await graph.ainvoke({"messages": [HumanMessage("again")]})
    assert "reached" not in out
    tm = [m for m in out["messages"] if isinstance(m, ToolMessage)][0]
    assert tm.content == BUDGET and tm.name == "consult_planning"
    assert out["messages"][-1].content == "I have what I need."


async def test_the_budget_is_per_domain():
    model = ScriptedChatModel(
        script=[tool_call("consult_nutrition", {"instruction": "Fuel Saturday's ride."})]
    )
    graph = outer_graph(model, make_handoff_tools(2, {"planning": 2}))
    out = await graph.ainvoke({"messages": [HumanMessage("fuel")]})
    assert out["reached"] == "nutrition"
```

`packages/tri-coach/tests/test_nodes.py`, append (it already imports `Brief`, `AIMessage`, `start_node`, `make_planning_node`, `make_nutrition_node`, `Recorder`, `CONFIG`):

```python
async def test_a_consultation_counts_against_its_domain_and_a_regeneration_does_not():
    asked = {"pending_changes": [], "messages": [AIMessage(content="Which day?")]}
    planning = make_planning_node(Recorder(asked))
    brief = Brief(domain="planning", instruction="x", tool_call_id="c1", message_id="m1")
    out = await planning({"brief": brief, "proposals": [], "consults": {"nutrition": 1}}, CONFIG)
    assert out["consults"] == {"nutrition": 1, "planning": 1}

    nothing = {"pending_changes": [], "pending_summary": "", "last_error": None}
    nutrition = make_nutrition_node(Recorder(nothing))
    regenerate = Brief(domain="nutrition", instruction="regenerate", regenerate=True)
    out = await nutrition(
        {"brief": regenerate, "proposals": [], "consults": {"nutrition": 2}}, CONFIG
    )
    assert "consults" not in out  # the follow-on is not a consultation
    consult = Brief(domain="nutrition", instruction="x", tool_call_id="c2", message_id="m2")
    out = await nutrition({"brief": consult, "proposals": []}, CONFIG)  # no key yet
    assert out["consults"] == {"nutrition": 1}


def test_a_new_turn_resets_the_consults():
    assert start_node({"consults": {"planning": 2}})["consults"] == {}
```

`packages/tri-coach/tests/test_prompt.py`: add `from dataclasses import replace`; in `test_prompt_order_is_rules_context_memory_and_names_the_limit` change `"at most 2 consultations per domain per turn"` to `"2 consultations per domain per turn"` and `PROMPT_VERSION == "3"` to `PROMPT_VERSION == "4"`; add `"returns a budget message"` to the phrase list in `test_rules_cover_policy_routing_and_memory`; append:

```python
def test_the_context_names_the_consults_left_this_turn():
    entries = [M.MemoryEntry(id="ab12cd", kind="injury", text="Knee.", created=date(2026, 9, 10))]
    assert "Consults left" not in render_system_prompt(ctx(), entries, max_consults=2)
    left = replace(ctx(), consults_left={"planning": 0, "nutrition": 2})
    text = render_system_prompt(left, entries, max_consults=2)
    assert "Consults left this turn: planning 0, nutrition 2." in text
    assert text.index("Today is") < text.index("Consults left") < text.index("Athlete memory")
```

`packages/tri-coach/tests/test_graph.py`: add `from pydantic import Field` and append:

```python
class Spy(ScriptedChatModel):
    """Records the system prompt of every call."""

    prompts: list[str] = Field(default_factory=list)

    def _generate(self, messages, *a, **k):
        self.prompts.append(messages[0].content)
        return super()._generate(messages, *a, **k)


async def test_the_consult_budget_holds_for_the_turn_and_resets_on_the_next(
    nocommit, make_deps, mem_store
):
    seed_active_plan(nocommit)
    coach = Spy(
        script=[
            consult("planning", "Lighten the week.", "c1"),
            consult("planning", "Lighten it more.", "c2"),
            AIMessage(content="Planning asked which session hurt; which was it?"),
            consult("planning", "The run hurt; drop Thursday's run.", "c3"),
            AIMessage(content="Planning asked again."),
        ]
    )
    ask = AIMessage(content="Which session hurt: the run or the ride?")
    planning = ScriptedChatModel(script=[ask, ask])
    deps = make_deps(
        tp=FakeTp(),
        coach=coach,
        planning=planning,
        nutrition=ScriptedChatModel(script=[]),
        analyst=ScriptedChatModel(script=[]),
        max_consults=1,
    )
    graph = build_graph(deps, InMemorySaver(serde=make_serde(STATE_TYPES)), mem_store)
    out = await graph.ainvoke({"messages": [HumanMessage("tired")]}, CFG)
    spent = [m for m in out["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "c2"]
    assert spent[0].content.startswith("consult budget for planning is spent this turn (1 of 1)")
    assert planning.calls == 1 and out["consults"] == {"planning": 1}
    assert "Consults left this turn: planning 1, nutrition 1." in coach.prompts[0]
    assert "Consults left this turn: planning 0, nutrition 1." in coach.prompts[1]

    out = await graph.ainvoke({"messages": [HumanMessage("the run")]}, CFG)
    assert planning.calls == 2 and out["consults"] == {"planning": 1}


async def test_a_thread_without_consults_runs_with_a_full_budget(nocommit, make_deps, mem_store):
    """A thread saved before the budget existed, resumed into `coach` without passing `start`."""
    graph, models = graph_for(
        make_deps, mem_store, coach=[AIMessage(content="Hello again.")]
    )
    await graph.aupdate_state(CFG, {"messages": [HumanMessage("hi")]}, as_node="start")
    assert "consults" not in (await graph.aget_state(CFG)).values
    out = await graph.ainvoke(None, CFG)
    assert out["messages"][-1].content == "Hello again." and models["coach"].calls == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_tools.py packages/tri-coach/tests/test_nodes.py packages/tri-coach/tests/test_prompt.py packages/tri-coach/tests/test_graph.py -v -k "budget or consults or domain or full_budget or limit or policy"`
Expected: FAIL. `make_handoff_tools` takes no arguments (`TypeError`), `consults` is missing from node output and `start_node`, `CoachContext` has no `consults_left`, the prompt still says "at most" and version 3.

- [ ] **Step 3: State and `start_node`**

`graph/state.py`, in `CoachState` after `next_proposal_id`:

```python
    consults: dict[str, int]  # consultations made this turn, by domain; start clears it
```

`graph/graph.py`, in `start_node`'s returned dict after `"next_proposal_id": 1,`: `"consults": {},`. Its docstring's first sentence becomes: `A new athlete turn: forget last turn's brief, proposals, decision and consult counts.`

- [ ] **Step 4: The handoff tools refuse past the budget**

In `tools/handoff.py`, add `from collections.abc import Mapping, Sequence` (replacing the `Sequence` import), and replace `_consult` and the two consult tools inside `make_handoff_tools`:

```python
CONSULT_BUDGET_SPENT = (
    "consult budget for {domain} is spent this turn ({n} of {n}); explain what you have and "
    "stop, or ask the athlete"
)


def _consult(
    domain: Domain,
    instruction: str,
    tool_call_id: str,
    messages: Sequence[AnyMessage],
    spent: int,
    max_consults: int | None,
) -> Command[str] | ToolMessage:
    if max_consults is not None and spent >= max_consults:
        # a plain tool result: the coach stays in its loop and answers with what it has
        return ToolMessage(
            content=CONSULT_BUDGET_SPENT.format(domain=domain, n=max_consults),
            tool_call_id=tool_call_id,
            name=f"consult_{domain}",
        )
    message_id = str(uuid4())
    ack = ToolMessage(
        content=f"{domain} consulted; its answer replaces this message.",
        tool_call_id=tool_call_id,
        name=f"consult_{domain}",
        id=message_id,
    )
    brief = Brief(
        domain=domain, instruction=instruction, tool_call_id=tool_call_id, message_id=message_id
    )
    return handoff(
        domain, tool_call_id=tool_call_id, messages=messages, ack=ack, update={"brief": brief}
    )


def make_handoff_tools(
    max_consults: int | None = None, spent: Mapping[str, int] | None = None
) -> list[BaseTool]:
    """The coach's handoff tools. `spent` is this turn's consultations by domain (the coach node
    reads it from state on every entry); past `max_consults` a consult returns the budget message
    instead of handing off. With no arguments the tools are unlimited (evals, tests)."""
    used = dict(spent or {})

    @tool
    def consult_planning(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str] | ToolMessage:
        """Brief the planning agent to change the calendar, the goal or the horizon. The
        instruction must name the signal, the lever and the constraint. The result (a proposal
        id with its summary, or the agent's question) comes back as this call's result."""
        return _consult(
            "planning", instruction, tool_call_id, messages, used.get("planning", 0), max_consults
        )

    @tool
    def consult_nutrition(
        instruction: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        messages: Annotated[list[AnyMessage], InjectedState("messages")],
    ) -> Command[str] | ToolMessage:
        """Brief the nutrition agent to change daily targets, fueling notes, the profile or the
        race plan. The instruction must name the signal, the lever and the constraint. The
        result comes back as this call's result."""
        return _consult(
            "nutrition", instruction, tool_call_id, messages, used.get("nutrition", 0), max_consults
        )
```

(`propose_changes` and the `return [...]` stay as they are.)

- [ ] **Step 5: The sub-graph nodes count**

`graph/nodes/planning.py`: add `Domain` to the `tri_coach.models` import and, below `keyed_violations`:

```python
def counted(state: CoachState, domain: Domain) -> dict[str, int]:
    """This turn's consult counts with one more for `domain`. A thread saved before the budget
    existed has no counts yet."""
    spent = dict(state.get("consults") or {})
    spent[domain] = spent.get(domain, 0) + 1
    return spent
```

In `make_planning_node`'s returned dict add `"consults": counted(state, "planning"),`. In `graph/nodes/nutrition.py`, import `counted` alongside `keyed_violations, result_message`, and add `"consults": counted(state, "nutrition"),` to the consultation path's returned dict only (not the `brief.regenerate` return).

- [ ] **Step 6: The coach node and the context line**

`context.py`: `CoachContext` gains, after `labs_missing`:

```python
    consults_left: dict[str, int] | None = None  # set by the coach node on every entry
```

Add below `_pending_line`:

```python
def _consults_line(left: dict[str, int] | None) -> str | None:
    if left is None:
        return None
    return (
        f"Consults left this turn: planning {left.get('planning', 0)}, "
        f"nutrition {left.get('nutrition', 0)}."
    )
```

and in `render_context`, before the pending line:

```python
    consults = _consults_line(ctx.consults_left)
    if consults:
        lines.append(consults)
```

`graph/nodes/coach.py`: add `from dataclasses import replace`, build the handoff tools per entry, and set the counts on the context. Replace `tools = [analyst, *wellness, *make_handoff_tools(), *make_memory_tools(deps.today)]` with `memory_tools = make_memory_tools(deps.today)`, and the body of `coach` from `with deps.connect()` through `agent = ...`:

```python
        spent = state.get("consults") or {}
        with deps.connect() as conn:
            ctx = await load_context(
                conn, store, deps.today(), state.get("pending"), labs_enabled=labs_enabled
            )
        left = {d: max(0, deps.max_consults - spent.get(d, 0)) for d in ("planning", "nutrition")}
        ctx = replace(ctx, consults_left=left)
        entries = await M.get_entries(store)
        prompt = render_system_prompt(ctx, entries, max_consults=deps.max_consults)
        # rebuilt on every entry: the counts change after each consultation
        tools = [
            analyst,
            *wellness,
            *make_handoff_tools(deps.max_consults, spent),
            *memory_tools,
        ]
        agent = make_subagent(deps.model, tools, prompt, middleware=[one_tool_call_at_a_time])
```

- [ ] **Step 7: The rule and the version**

`prompts/coach.py`: `PROMPT_VERSION = "4"`, and in `COACH_RULES` replace

```
- Make at most {max_consults} consultations per domain per turn; then explain what you found and
  stop. If a sub-agent asks a question instead of proposing, answer it from the conversation and
  memory and consult again with a fuller brief, or ask the athlete.
```

with

```
- You have {max_consults} consultations per domain per turn; the context shows how many are
  left. A consult past that returns a budget message instead of a result: then explain what you
  found and stop, or ask the athlete. If a sub-agent asks a question instead of proposing, answer
  it from the conversation and memory and consult again with a fuller brief, or ask the athlete.
```

- [ ] **Step 8: Run the coach suite**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass. If `test_evals.py` pins an experiment name, it reads `PROMPT_VERSION` and follows it.

- [ ] **Step 9: Commit**

```bash
uv run ruff format packages/tri-coach
git add packages/tri-coach
git commit -m "feat(coach): enforce the per-turn consult budget; context shows consults left; prompt v4"
```

---

### Task 5: The coach names what was not proposed

**Files:**
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/planning.py` (`keyed_violations`, `proposal_from_planning`)
- Modify: `packages/tri-coach/src/tri_coach/graph/nodes/nutrition.py` (`proposal_from_nutrition`)
- Modify: `packages/tri-coach/src/tri_coach/models.py` (`Proposal.render`)
- Modify: `packages/tri-coach/src/tri_coach/prompts/coach.py` (the consultation-result rule)
- Test: `packages/tri-coach/tests/test_nodes.py`, `packages/tri-coach/tests/test_models.py`, `packages/tri-coach/tests/test_prompt.py`

**Interfaces:**
- Consumes: `PROMPT_VERSION = "4"` (Task 4; not bumped again).
- Produces: `keyed_violations` lines `<where> not proposed: <v>`; a no-change proposal with `pending_violations` has `question=None` and renders `<id> (<domain>) proposed no changes` + `violations: …`.

- [ ] **Step 1: Write the failing tests**

`packages/tri-coach/tests/test_nodes.py`:
- In `test_a_consultation_carries_the_planning_violations_by_week`: `p.violations == ["week of 2026-09-21 not proposed: hard sessions on consecutive days"]` and `line = "violations: week of 2026-09-21 not proposed: hard sessions on consecutive days"`.
- In `test_nutrition_proposals_carry_fuel_violations_by_session_and_race`: the expected list becomes `["race note not proposed: no sodium", "session w2 not proposed: carbs 95 g/h above the 90 g/h ceiling"]`.
- In `test_a_no_change_planning_proposal_keeps_its_refused_weeks` and `test_a_no_change_nutrition_proposal_keeps_its_refused_notes`: `p.question == "Nothing can be written."` becomes `p.question is None` (the rest stays).

`packages/tri-coach/tests/test_models.py`, append (add `Proposal` to its `tri_coach.models` import if missing):

```python
def test_a_proposal_with_everything_refused_says_it_proposed_nothing():
    p = Proposal(
        id="p1",
        domain="planning",
        summary="week 2026-09-21: not designed: hard sessions on consecutive days",
        violations=["week of 2026-09-21 not proposed: hard sessions on consecutive days"],
        pending_violations={"2026-09-21": ["hard sessions on consecutive days"]},
    )
    assert p.render() == (
        "p1 (planning) proposed no changes\n"
        "violations: week of 2026-09-21 not proposed: hard sessions on consecutive days"
    )
```

`packages/tri-coach/tests/test_prompt.py`: add `"not proposed"` to the phrase list in `test_rules_cover_policy_routing_and_memory`.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest packages/tri-coach/tests/test_nodes.py packages/tri-coach/tests/test_models.py packages/tri-coach/tests/test_prompt.py -v`
Expected: the changed and new tests FAIL (old wording, `question` still set, render still "asked instead").

- [ ] **Step 3: Implement**

`graph/nodes/planning.py`, `keyed_violations`: the keyed line becomes `lines += [f"{where(k)} not proposed: " + "; ".join(keyed[k]) for k in sorted(keyed)]`, and its docstring's "one line per `pending_violations` entry" gains "(a week or note the sub-graph refused and did not propose)". In `proposal_from_planning`, change `if not changes:` to `if not changes and not keyed:` and add, before it:

```python
    if not changes and keyed:
        # every week was refused: not a question, the violations say why
        return Proposal(
            id=pid,
            domain="planning",
            summary=out.get("pending_summary") or "",
            violations=violations,
            pending_violations=keyed,
        )
```

`graph/nodes/nutrition.py`, `proposal_from_nutrition`: the same two edits with `domain="nutrition"`.

`models.py`, `Proposal.render`, after the `question` branch:

```python
        if not self.changes and self.pending_violations:
            return f"{self.id} ({self.domain}) proposed no changes\n" + (
                "violations: " + "; ".join(self.violations)
            )
```

`prompts/coach.py`, in `COACH_RULES` replace

```
  When it carries violations, state them in your narration or consult again with a revised brief.
```

with

```
  When it carries violations, state them in your narration or consult again with a revised brief.
  A line "... not proposed: ..." names a week or note the sub-agent refused because it still broke
  a rule after its retry; it is not in the proposal. Tell the athlete which rule, and consult
  again only when you can name what to change.
```

- [ ] **Step 4: Run the coach suite**

Run: `uv run pytest packages/tri-coach -q`
Expected: all pass. The check-in lines (`p1 week of <w>: not proposed: …`, `skipping p1 week of <w>: …`) are built from `pending_violations`, not from these lines, and do not change.

- [ ] **Step 5: Commit**

```bash
uv run ruff format packages/tri-coach
git add packages/tri-coach
git commit -m "feat(coach): proposals name refused weeks and notes as not proposed"
```

---

### Task 6: Docs, full checks, vault copies, hand-off

**Files:**
- Modify: `packages/tri-coach/README.md`, `packages/tri-planning/README.md`, `packages/tri-nutrition/README.md`
- Modify (mirror): the vault copies under `/Users/brian/Documents/dev-vault/projects/paradigm/fitness_agents/triathlon_agent/` of every repo markdown file this branch changed (`packages/*/readme.md`, `docs/architecture/harness.md`), plus this plan at `docs/superpowers/plans/2026-09-27-guardrails-02-consults-and-held-reviews.md`

- [ ] **Step 1: README edits**

`packages/tri-coach/README.md`:
- The `start` row's "clears" list gains `consults`.
- The `planning` and `nutrition` rows' output column gains `, `consults` + 1 for the domain` (nutrition: "on a consultation; the regenerate brief does not count").
- After the invariants paragraph, add:

```
The coach may consult each sub-agent `TRI_COACH_MAX_CONSULTS_PER_DOMAIN` times per turn
(default 2). `start` clears the counts; the context block shows `Consults left this turn`, and a
consult past the budget returns a budget message instead of handing off, so the coach answers
with what it has. The follow-on regeneration after an apply is not a consultation.
```

`packages/tri-planning/README.md`, after the `In chat:` paragraph, add: `A review left waiting from an earlier session opens first, before chat reads a message.`

`packages/tri-nutrition/README.md`: in the `tri-nutrition chat` bullet, append ` A review left waiting from an earlier session opens first.`; in the check-in bullet, replace `A review\n  left by an earlier run is shown but never approved here (exit 3): answer it in `chat`.` with `A review\n  left by an earlier run, a partial apply's remainder, or a run stopped mid-graph is shown and\n  never approved here (exit 3): answer it in `chat`.`

- [ ] **Step 2: Full checks, in the Definition of Done order**

```bash
uv run pytest -q -rs
uv run ruff format --check . && uv run ruff check . && uv run mypy
(cd web && npm run lint && npm test && npm run build)
```

Expected: pytest all pass, `SKIPPED` only for `needs --live`; ruff and mypy clean; the web checks pass (untouched).

- [ ] **Step 3: Vault copies**

For each changed markdown file, `diff` the repo file against its vault copy first. If they matched before this branch (compare against `git show main:<path>`), copy the repo file over; if the vault copy had drifted, apply only this branch's edits and tell Brian. Copy this plan to `docs/superpowers/plans/` in the vault.

- [ ] **Step 4: Commit**

```bash
git add packages/tri-coach/README.md packages/tri-planning/README.md packages/tri-nutrition/README.md
git commit -m "docs: consult budget, a waiting review opens first, nutrition check-in refuses a busy thread"
```

- [ ] **Step 5: Hand-off for Brian**

Tell Brian:
- `uv run tri-coach eval` now names the experiment `coach-v4`; compare it with the last `coach-v3` run. It needs `LANGSMITH_API_KEY` and `ANTHROPIC_API_KEY` and costs model calls.
- Optional, his to run: the checkpoints earlier consultations wrote on thread `coach` under sub-graph namespaces are dead weight. After confirming the database endpoint:

```sql
delete from checkpoint_writes where thread_id = 'coach' and (checkpoint_ns like 'planning:%' or checkpoint_ns like 'nutrition:%');
delete from checkpoint_blobs  where thread_id = 'coach' and (checkpoint_ns like 'planning:%' or checkpoint_ns like 'nutrition:%');
delete from checkpoints       where thread_id = 'coach' and (checkpoint_ns like 'planning:%' or checkpoint_ns like 'nutrition:%');
```
