# tri-coach — The Coaching Orchestrator (package `tri_coach`)

**Date:** 2026-09-11
**Status:** Approved design; milestone 1 merged 2026-09-12 (plan 01), milestone 2 in progress (plan 02); revised 2026-09-11 against `main` at d66a54b after planning plan 4 landed (see §1, §7.3, §8, §13)
**Purpose:** The agent the athlete talks to. It answers questions by consulting the analyst, decides on its own authority when a change to the training plan or the nutrition targets is warranted, briefs the planning and nutrition agents to produce that change, and presents one change set for approval. It is the sole decider: sub-agents never initiate a change under the coach.

Companion specs: `tri-analyze` (2026-09-06), `tri-planning` (2026-09-07), `tri-nutrition` (2026-09-10). Both the planning and nutrition specs deferred "an orchestrator composing the agents as subgraphs" to this spec. The `tri-wellness` spec (2026-09-10) is not composed here; see §14.

## 1. Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Authority | The coach proposes, the athlete approves. One review gate, owned by the coach. Nothing is written until the athlete approves. | Keeps the write-safety invariant every agent was built on while making the coach the only place that decides *when* and *how* to adjust. |
| Athletes | Single athlete, as every existing agent. | No identity plumbing exists; adding it is a separate project. |
| Entry points | The coach is the front door. Per-agent chats stay for debugging and inspection; nothing is removed. | Working tools are kept; the coach adds a layer. |
| Memory | Coach-owned athlete memory in the LangGraph Store under `("athlete", "coach")`. | What the athlete says in conversation (injuries, travel, preferences, how they like to be coached) must shape later decisions and is stored by no sub-agent. |
| Composition | Sub-graphs run in a propose mode that ends with `pending_changes` and has no review or apply; the coach owns review and dispatches apply. | The coach reads every proposal before the athlete sees it. Subgraph composition, interrupt handling and supervisor handoffs are all exercised. |
| Planning milestone 4 | Plan 4 is complete on `main` (adjust sub-agent, `propose_calendar_changes`, `design_next_week`, `tri-planning check-in`, the design-prompt evaluator, the live TrainingPeaks test). This spec adds a *directed* mode to its adjust sub-agent: when the message is a brief from the head coach it satisfies that brief and nothing else; the self-directed weekly checklist and `tri-planning check-in` stay as the standalone path. | Same treatment as nutrition's check-in: the standalone command is a debugging path, and under the coach only the coach decides what to change. |
| Proactive path | One `tri-coach check-in [--yes]` command syncs, runs the merged checklist and pauses at one gate. `tri-nutrition today` stays the daily Garmin write. | Replaces running the per-agent check-ins separately. |
| Sub-agent patterns | The analyst is a tool (agent-as-tool). Planning and nutrition are handoffs (`Command(goto=..., graph=Command.PARENT)` from a tool inside `create_agent`). | A tool fits when the result is text; a handoff fits when the sub-graph's output must land in the parent state and drive routing. Having both side by side is a learning goal. |
| Interface | Terminal REPL and CLI | Same as the other agents. |
| LLM | `claude-opus-5` via `langchain-anthropic` | Same as the other agents. |
| Learning goals | Subgraph composition and interrupt propagation; supervisor and handoff patterns; cross-agent memory in the Store; multi-turn evaluation in LangSmith. | Chosen 2026-09-11. |

## 2. Feasibility, verified 2026-09-11

Installed: langgraph 1.2.11, langgraph-prebuilt 1.1.0, langchain 1.4.0, langchain-anthropic 1.7.1, langchain-mcp-adapters 0.3.2, langsmith 0.12.2.

- `langgraph.prebuilt.tool_node` forwards a `Command` returned by a tool; when `command.graph is Command.PARENT` it re-emits a parent-level `Command(goto=...)`. A handoff tool inside a `create_agent` loop can therefore route the outer `StateGraph`. `create_agent` is compiled with `checkpointer=False` by `make_subagent`, as in the existing conversational nodes. Re-verified 2026-09-11: the parent command travels as a `ParentCommand` exception, and `langgraph/pregel/_retry.py` retargets a `Command.PARENT` command to the enclosing namespace as it bubbles, so it should reach the coach graph even when the sub-agent is invoked from inside a node function rather than added as a node (§15 keeps the test).
- A compiled graph invoked from a node function is a subgraph: its checkpoint namespace is `<node>:<task_id>` and the task id is minted per superstep (`langgraph/pregel/main.py`), so a fresh invocation sees only what the parent passes in. This is why consultations are stateless (§6.2) and why long-lived planning state must come from the database (§7.1).
- `Command(resume=...)` accepts a single value or a mapping of interrupt ids to values. The coach uses a single `review` interrupt, so the single-value form suffices.
- Nutrition's `apply.py` already has a standalone `write_change(deps, thread_id, change)`; planning's apply is inline in the node closure and is lifted (§7.1). Planning's `repo` exposes `get_active_goal` and `get_active_plan(goal_id)`, enough to derive phase.
- Nutrition targets are built from `plan_weeks.designed` and `workouts`, i.e. from the *stored* plan. A nutrition regeneration is only correct after a plan change has been applied. The coach therefore presents a plan change and its nutrition consequence as two sequential gates in one command (§6.5), never as one.
- `tri_core.mcp.live_tools.open_live_tools(specs, log)` (added to `main` after this spec was first written) opens one adapters session per server, converts each server tool's input schema to a `BaseTool`, and keeps the allow-listed ones; planning's `chat` already binds Garmin through it. The `ToolCaller` protocol the graphs' deps hold (`tri_core.sync.ToolCaller`, one method `call_json(tool, args)`) can be satisfied over those same tools, so one process needs one session per server (§7.3).

## 3. System overview

```
                       ┌─────────────────────────────────────────────────────┐
  garmin_mcp ─────────►│  tri-coach                                          │
  (one session, the    │  LangGraph StateGraph, thread "coach"               │
   union allow-list)   │                                                     │
  tp_mcp ─────────────►│   coach ──► ask_analyst ──► tri-analyze agent (tool)│
  (one session)        │     │                                               │
                       │     ├──► planning  (tri-planning graph, propose mode)│
  Postgres ◄──────────►│     ├──► nutrition (tri-nutrition graph, propose mode)
  (all tables,         │     │                                               │
   checkpoints,        │     └──► review ──► apply ──► planning.apply_changes│
   Store: coach and    │          interrupt()          nutrition.apply_changes│
   nutrition           └─────────────────────────────────────────────────────┘
   namespaces)                    ▲
                                  │ tri-coach chat | check-in | memory | reset
```

## 4. Package layout

```
packages/tri-coach/
  pyproject.toml                 tri-coach; depends on tri-core, tri-analyze, tri-planning,
                                 tri-nutrition; script tri-coach
  src/tri_coach/
    cli.py                       chat, check-in, memory, reset
    config.py                    TRI_COACH_LANGSMITH_PROJECT (tri_coach), consult limits
    allowlist.py                 union of the sub-agents' Garmin server tools; analyst read tools
    servers.py                   open_servers(stack, settings, no_live) -> Servers: the Garmin and
                                 TrainingPeaks tools from one open_live_tools call over the union
                                 allow-list, plus a ToolsCaller per server (§7.3); builds each
                                 package's GraphDeps from them
    memory.py                    MemoryEntry; NAMESPACE = ("athlete", "coach"); get/put/forget;
                                 render(entries, today)
    context.py                   CoachContext loaded from the database and the Stores;
                                 render_context(ctx) for the system prompt
    models.py                    Brief, Proposal, ChangeSet, ReviewDecision, ApplyReport
    graph/
      state.py                   CoachState TypedDict
      deps.py                    CoachDeps: model, connect, db_url, servers, store,
                                 planning_deps, nutrition_deps, analyst_tools, today
      llm.py                     make_model, make_subagent (copied from nutrition)
      checkpointer.py            open_checkpointer with the state's Pydantic types registered
      graph.py                   build_graph(deps, checkpointer, store)
      nodes/
        coach.py                 create_agent sub-agent; prompt rendered per turn
        planning.py              runs tri_planning.build_graph(..., embedded=True) on the brief
        nutrition.py             runs tri_nutrition.build_graph(..., embedded=True) on the brief
        review.py                interrupt(); returns ReviewDecision
        apply.py                 dispatch to planning.apply_changes then nutrition.apply_changes
    tools/
      analyst.py                 ask_analyst
      handoff.py                 consult_planning, consult_nutrition, propose_changes
      memory.py                  remember, forget
    prompts/
      coach.py                   rules, decision policy, routing guide, check-in checklist,
                                 PROMPT_VERSION
    evals/
      cases.py, evaluators.py, run.py
    repl.py                      streaming loop with nested namespaces, review dialogue,
                                 combined YAML edit, /status /memory /pending /tools /prompt
  tests/
```

Dependency direction: `tri-coach` depends on all four packages. No existing package depends on another; that rule is unchanged.

## 5. Data model

### 5.1 The Store (coach memory)

Namespace `("athlete", "coach")`, one key `memory`, value `{"entries": [MemoryEntry, ...]}`.

```python
class MemoryEntry(BaseModel):
    id: str                                # short random id, printed by /memory
    kind: Literal["injury", "constraint", "preference", "event", "coaching_style", "note", "checkin"]
    text: str
    created: date
    until: date | None = None              # an injury or event with a known end
```

`remember` appends; `forget` removes by id; rendering drops entries whose `until` is before today. A `checkin` entry is one paragraph the coach writes at the end of each check-in (what was found, what was decided, what to watch) with `until` fourteen days out, so the next check-in and a chat after `reset` both know what the last one decided; the check-in checklist (§8) ends with writing it. The whole list is rendered into the coach prompt, so there is no recall tool. The prompt tells the coach what to remember: anything the athlete says that should shape a future decision and is not already stored by planning (goal, availability, constraints) or nutrition (profile). `reset --forget-memory` deletes the key. Nutrition's namespace `("athlete", "nutrition")` is read by the context loader and never written by the coach.

### 5.2 Tables

None new. The coach writes nothing to the database directly. Planning and nutrition writes go through their packages' `apply_changes`, which record `plan_changes` and `nutrition_changes` rows exactly as today, with `thread_id = "coach"`. Checkpoints live in the existing checkpoint tables under thread `coach`.

### 5.3 Models

```python
class Brief(BaseModel):
    domain: Literal["planning", "nutrition"]
    instruction: str                       # the coach's bounded instruction
    regenerate: bool = False               # nutrition only: skip the sub-agent, go to targets

class Proposal(BaseModel):
    id: str                                # "p1", "p2", ... within the turn
    domain: Literal["planning", "nutrition"]
    summary: str                           # the sub-graph's pending_summary
    changes: list[CalendarChange] | list[NutritionChange]
    violations: list[str]                  # from the sub-graph's last_error or fuel violations
    question: str | None                   # set instead of changes when the sub-agent asked

class ChangeSet(BaseModel):
    narration: str                         # the coach's explanation shown at review
    proposals: list[Proposal]              # the ones the coach kept

class ReviewDecision(BaseModel):
    action: Literal["approve", "reject", "edit"]
    note: str | None = None
    proposals: list[Proposal] | None = None  # on edit: the YAML round trip, both domains

class ApplyReport(BaseModel):
    domain: Literal["planning", "nutrition"]
    applied: int
    skipped: list[str]
    remaining: int
    error: str | None
    sessions_changed: bool                 # planning: any create/update/delete/move applied
```

`CalendarChange` and `NutritionChange` are imported from their packages; the YAML edit round trip serializes both under their domain key.

## 6. The graph

### 6.1 State

```python
class CoachState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    brief: Brief | None                    # set by a handoff tool, consumed by planning/nutrition
    proposals: list[Proposal]              # accumulated this turn
    pending: ChangeSet | None              # what review shows
    review_decision: ReviewDecision | None
    last_error: str | None
    regenerate_after_apply: bool
```

`brief`, `proposals` and `pending` are cleared by the coach node at the start of each athlete turn. Persisted per thread by `AsyncPostgresSaver` on thread `coach`; the Store is passed to `compile(store=...)`.

### 6.2 Consultations are stateless

Each handoff runs the sub-graph fresh with a single `HumanMessage` carrying the brief. The sub-graph either produces `pending_changes` or ends its turn with a question or a report in its last `AIMessage`. The planning or nutrition node maps that output into one `Proposal` (with `changes` or `question`) and appends a short `AIMessage` to the coach's messages naming the proposal id and summary. The coach answers a question from its own conversation and memory, or asks the athlete, and hands off again next turn with a fuller brief. The coach thread is the only conversational memory. Multi-turn intakes (a new training goal, a new nutrition profile) therefore happen as a conversation with the coach, which briefs the sub-agent with everything gathered; the sub-agent's intake tool validates and saves, or asks for what is missing.

### 6.3 Nodes and edges

```
START     -> coach
coach     -> planning | nutrition   (a handoff tool returned Command(goto=..., graph=PARENT))
coach     -> review                 (propose_changes was called)
coach     -> END                    (turn ended in conversation)
planning  -> coach
nutrition -> coach
review    -> apply                  (approve or edit)
review    -> coach                  (reject; note appended as a HumanMessage)
apply     -> nutrition              (regenerate_after_apply: planning changed sessions and
                                     nutrition targets exist in the horizon)
apply     -> END
```

- **coach**: a `create_agent` sub-agent built with `make_subagent`, the same helper the intake and check-in nodes use. Its system prompt is rendered per turn: the stable part first (persona, decision policy, routing guide, check-in checklist), then the context block (§6.4), then memory. Tools, and nothing else:
  - `ask_analyst(question)`: runs `tri_analyze.agent.build_agent` over `query_training_db` and the analyst read tools built from the coach's own sessions (§7.3), on a throwaway `InMemorySaver` thread, and returns the final text. Agent-as-tool.
  - `consult_planning(instruction)`, `consult_nutrition(instruction)`: return `Command(goto=<node>, graph=Command.PARENT, update={"brief": Brief(...), "messages": [ToolMessage(ack)]})`. Handoff. The `ToolMessage` closes the tool call so the message history stays valid.
  - `propose_changes(narration, proposal_ids)`: selects proposals by id, sets `pending`, and returns a `ToolMessage`; the route after the coach node goes to `review` when `pending` is set. The coach never edits a change payload; if it wants something different it re-consults with a revised instruction. The athlete can edit YAML at review.
  - `remember(kind, text, until?)`, `forget(id)`: coach memory (§5.1), through the injected Store.
- **planning**: builds `tri_planning.graph.build_graph(planning_deps, checkpointer, embedded=True)` once at start-up and invokes it with `{"messages": [HumanMessage(brief.instruction)]}`. Maps the output to a `Proposal`: `pending_changes` and `pending_summary` when present, else the last `AIMessage` text as `question`; `last_error` and validator notes as `violations`.
- **nutrition**: same over `tri_nutrition.graph.build_graph(nutrition_deps, checkpointer, store, embedded=True)`. When `brief.regenerate` is set it invokes with `{"targets_requested": True, "regenerate_from": "checkin"}` and no message, which routes straight to `targets` (§7.2).
- **review**: `interrupt({"narration", "proposals"})`. Resume is `Command(resume=ReviewDecision)`. On reject the note is appended as a `HumanMessage` and the coach node runs again, so the coach can re-consult or explain.
- **apply**: for each domain with kept proposals, in the order planning then nutrition, calls that package's `apply_changes` with `thread_id = "coach"` and collects an `ApplyReport`. Appends one report message. Sets `regenerate_after_apply` when planning reported `sessions_changed` and `nutrition_targets` has rows in the horizon. Remaining changes and errors stay in `pending` so a later turn can re-propose them.

Invariants, all preserved by construction: no write tool is ever bound to a model; the only edge into either package's `apply_changes` is the coach's `review`; sub-graphs in embedded mode contain no review or apply nodes; consultations write only what the sub-graphs' standalone runs write before review: their working tables (`training_plans`, `plan_weeks.designed`, `nutrition_targets`, `fuel_plans`), a goal row from `set_training_goal`, and the nutrition profile in the Store from `save_nutrition_profile`; never Garmin or TrainingPeaks.

### 6.4 The coach prompt

Stable part, in this order so prompt caching covers it:

1. Persona: the athlete's head coach; direct, specific, no generic encouragement (the analyst's feedback rules apply to the coach's own prose too).
2. Decision policy. Sub-agents never initiate a change. A change is warranted only when the coach can name the signal (from context, the analyst, or what the athlete said), the lever, and the constraint. The brief names all three, for example: "Knee pain reported today. No running for 7 days, hold weekly TSS within 10 percent of target, keep Saturday's ride." Pure questions never trigger a consultation. At most two consultations per domain per turn; then explain and stop.
3. Routing guide: analyst for anything about past sessions, trends, readiness, sleep, comparisons to plan; planning for anything that changes the calendar, the goal or the horizon; nutrition for anything that changes targets, fueling notes, the profile or the race plan; both, in that order, when a plan change alters training load.
4. Memory policy: what to `remember`, what not to (nothing the sub-agents already store), and to say when a memory entry influenced a decision.
5. The check-in checklist (§8), used when the message is the fixed check-in request.

Context block, rendered per turn from the database and the two Store namespaces: today; athlete thresholds; active goal, plan phase, this week's target versus actual TSS and hours, designed weeks remaining; nutrition goal, weight and body fat trend, targets through date; the last seven days of load and recovery; then memory entries. The coach has no data tool of its own; anything deeper goes through `ask_analyst`.

`PROMPT_VERSION` in `prompts/coach.py` is bumped whenever the prompt changes and names the LangSmith experiment (§12).

### 6.5 The follow-on gate

After `apply` sets `regenerate_after_apply`, the nutrition node runs with a regenerate brief, its proposal (new day targets for today if changed, and fueling notes for changed sessions) returns to the coach, and the coach narrates the consequence and calls `propose_changes` again. The athlete sees a second gate in the same command. When regeneration changes nothing, the coach says so and the turn ends. This is the only path where two gates occur in one turn, and it exists because nutrition targets are derived from the stored plan (§2).

## 7. Changes to existing packages

### 7.1 tri-planning

- **`route` node.** `START -> route` derives `phase`, `goal_id` and `plan_id` each run from the database: no active goal is `intake`; an active goal without an active plan is `planning`; an active plan is `active`. All three are needed because a stateless consultation starts with empty state and the `adjust` node asserts `plan_id` while `apply` reads both ids. The thread no longer carries them. `route_start` keeps its `pending_changes -> review` rule. Standalone `tri-planning chat` behaves as before.
- **Embedded mode.** `build_graph(deps, checkpointer, *, embedded=False)`. When `embedded` is true the `review` and `apply` nodes are not added and each conditional edge's path map sends `"review"` to `END`, leaving `pending_changes`, `pending_summary` and `changes_from` in the output state.
- **`apply_changes`.** `apply.py` becomes `apply_changes(deps, changes, thread_id, *, plan_id, goal_id, tp_plan_applied) -> ApplyResult` plus a thin node that reads those from state and calls it. `ApplyResult` carries applied, skipped, remaining, error, `tp_plan_applied` and `sessions_changed`. The coach passes `plan_id` and `goal_id` from the active rows.
- **Directed adjust.** Plan 4 is complete: the `adjust` sub-agent, `propose_calendar_changes` (ops restricted to create, update, move, delete), `design_next_week`, `tri-planning check-in` and the design-prompt evaluator are on `main`. This spec adds one thing: the adjust prompt gains a directed section. When the message is a brief from the head coach, the sub-agent satisfies that instruction with the minimal change set and nothing else; obeys `validate.week`, the lever order (swap days, shorten, downgrade intensity, drop, re-plan the week) and ownership (`athlete_requested` only when the brief says the athlete asked); and, when the instruction is ambiguous, asks one question and stops. The self-directed weekly checklist applies only to the fixed check-in request from `tri-planning check-in`. `adjust -> review` when changes were proposed, or `END` in embedded mode.

### 7.2 tri-nutrition

- **Embedded mode.** Same flag and path-map rule: `fuel` ends the graph, `targets` violations end it, `review` and `apply` are not added.
- **`apply_changes`.** `apply_changes(deps, store, changes, thread_id, *, overrides) -> ApplyResult` lifted from the node around the existing `write_change`; the node calls it.
- **Regenerate entry.** `route_start` returns `"targets"` when the input state has `targets_requested` set and carries no new `HumanMessage`. Used by the coach's regenerate brief; `tri-nutrition today` is unchanged.
- **Directed check-in.** The check-in prompt gains a section: when the message is a brief from the head coach, execute it and nothing else; the self-directed checklist applies only to the fixed check-in request from `tri-nutrition check-in`.

### 7.3 tri-core

- `tri_core.mcp.live_tools.open_live_tools` gains a sibling `open_live_servers(specs, log) -> dict[str, list[BaseTool]]` that returns the bound tools per server name over the same sessions (`open_live_tools` becomes the flattened view of it). `tri_core.mcp.caller.ToolsCaller(tools)` implements `ToolCaller` over a list of adapter tools: `call_json` finds the tool by name, awaits `tool.ainvoke(args)`, and passes the text through `parse_tool_text`, raising `McpToolError` exactly as `McpToolClient.call_json` does. The coach opens Garmin (with `enabled_tools` set to the union of the three packages' Garmin lists) and TrainingPeaks once, hands the tools to the analyst and to planning's `garmin_tools`, and hands a `ToolsCaller` per server to planning's `tp` and nutrition's `garmin` and `tp` deps. One process per server; the adapters already own schema conversion, so nothing is re-wrapped. Every existing CLI keeps its current binding.

## 8. Commands

- `tri-coach chat [--no-live]`: the REPL. Streams tokens and prints `→ tool(args)` and `← tool: N chars` as the other agents do; nested namespaces show which sub-graph is running. At review: the narration, then the changes grouped by domain (planning's week table, nutrition's day table and fueling lines, reusing each package's renderers), then `approve / reject <note> / edit`. `edit` opens one YAML document with both domains in `$EDITOR`. `/status` prints one line per domain (plan phase and this week; nutrition targets through; memory entries; next node). `/memory` prints memory as YAML. `/pending` re-prints a paused change set. `/sync` runs `tri sync`. `/tools` lists the bound tools. `/prompt` prints the rendered system prompt. `/quit`.
- `tri-coach check-in [--yes] [--no-sync] [--no-live]`: runs `tri sync`, sends the fixed check-in request on thread `coach`, prints the report and any proposed change set, and exits 3 while paused at review; `--yes` approves. Before sending, it reads the thread: if the graph is paused or `pending` is set it refuses with exit 3 and points to `/pending` in chat, the rule `tri-planning check-in` already enforces; if there is neither an active plan nor a nutrition profile it exits 2 with a message, matching planning's `EXIT_NO_PLAN`. Exit 1 on a model or API error. The checklist, in the coach prompt: last seven days planned versus actual; sessions with RPE at or above 8 or feeling at or below 3; 3-day readiness and HRV against the 30-day baseline; TSB entering the week; fewer than 2 designed weeks remaining (extend); logged intake versus targets by day type; weight and body fat trend against the goal rate; fewer than 7 days of targets remaining (extend); finally `remember(kind="checkin", ...)` with the one-paragraph summary (§5.1). The coach reads through `ask_analyst`, decides, briefs, proposes. A clean week ends with a short report, the memory entry, and no gate.
- `tri-coach memory [--forget ID]`: print memory, or remove one entry.
- `tri-coach reset [--yes] [--forget-memory]`: clears the coach thread. Never touches Garmin, TrainingPeaks, or the sub-agents' threads, tables or Store keys.
- Unchanged: `tri-nutrition today` remains the daily Garmin write. `tri-analyze chat`, `tri-planning chat`, `tri-planning check-in`, `tri-nutrition chat` and `tri-nutrition check-in` stay for debugging.

## 9. Error handling

| Failure | Behavior |
|---|---|
| Sub-agent asks instead of proposing | The proposal carries `question`; the coach answers it or asks the athlete, then re-consults |
| Sub-graph validation or bounds violation | The proposal carries `violations`; the prompt requires the coach to state them in the narration or re-consult |
| A server is unavailable | That package's `apply_changes` holds its changes pending, as today; the coach reports which domain is held; consultations that need a live read say so |
| Planning apply fails mid-batch | Nutrition dispatch still runs for nutrition-only proposals; the regenerate step is skipped; the report names the failed change; remaining changes stay pending |
| Analyst error | Returned as the tool result; the prompt forbids guessing at data the analyst could not read |
| Coach consults in a loop | Prompt rule of at most two consultations per domain per turn; `recursion_limit` on the run as the hard stop |
| Anthropic API error | Caught per turn, printed, the REPL continues; state at the last checkpoint |
| Checkpointer or Store tables missing | `chat` refuses to start and prints the setup command |

## 10. Configuration

`tri_core.config` is shared. `tri_coach.config` adds `TRI_COACH_LANGSMITH_PROJECT` (default `tri_coach`) and `TRI_COACH_MAX_CONSULTS_PER_DOMAIN` (default 2). No new dependencies. The root `pyproject.toml` adds `tri-coach` to the workspace sources, the mypy files list and ruff's first-party list.

## 11. Testing

- **Unit, no database, no model:** memory entry expiry and rendering; prompt rendering from a fixed context (byte-stable for a fixed input); proposal id assignment and selection; combined YAML edit round trip across both domains; `ApplyReport` from each package's `ApplyResult`; `ToolsCaller` over fake tools, including the empty-result and error text conventions `parse_tool_text` handles; the check-in refusal and exit codes against a scripted thread state.
- **Planning and nutrition, `ScriptedChatModel`:** embedded mode ends with `pending_changes` and the compiled graph has no `review` node; nutrition's regenerate entry routes to `targets`; planning's `route` derives all three phases from the database; the existing apply tests pass unchanged through the thin node and again through `apply_changes` directly; the directed adjust sub-agent ends on `propose_calendar_changes` and merges `design_next_week` output.
- **Coach graph, `ScriptedChatModel` at every level, sub-graphs scripted too, `InMemoryStore`:** a pure question calls `ask_analyst` and ends without a handoff; a handoff runs the planning node and its proposal lands in `proposals`; `propose_changes` reaches the review interrupt with the narration; approve dispatches to fakes in order and each package records its audit row with `thread_id = "coach"`; reject returns to the coach with the note in messages; a planning apply that changed sessions triggers the regenerate brief and a second gate; a sub-agent question returns as a proposal with `question`; `remember` writes the Store and the next rendered prompt contains the entry; a second process resumes the paused review from Postgres.
- **Database tests** use `tri_analyze_test` and the rolled-back `db` fixture. **Live, opt-in:** one coach turn with both servers up that answers a question through the analyst and consults nothing.
- Definition of done per task: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`.

## 12. Observability and evaluation

LangSmith tracing by env, project `tri_coach`. Handoff runs carry a `domain` tag; the check-in run carries `checkin`.

Dataset `tri_coach_routing`: single-turn cases whose inputs hold prior messages and a rendered context block, and whose outputs hold the expected trajectory. Evaluators: **routing accuracy** (the set of coach tools called matches the expected one of: none, analyst only, planning, nutrition, both); **no unrequested adjustment** (a case marked as a pure question produces no handoff); an **LLM judge** over each brief for being bounded and for naming the signal, the lever and the constraint. `tri-coach eval [--judge/--no-judge] [--prefix] [--recreate-dataset]` runs it as experiment `coach-v<PROMPT_VERSION>` and prints the pass rate per evaluator, as nutrition's eval does.

## 13. Milestones

1. **Sub-package preparation.** Planning `route` node with database-derived phase and ids; embedded mode and `apply_changes` in planning and nutrition; nutrition regenerate entry; the directed sections in planning's adjust prompt and nutrition's check-in prompt with their tests; `open_live_servers` and `ToolsCaller` in tri-core. No coach yet; every existing CLI behaves as before.
2. **Coach v1.** Package, state, coach node with memory, the analyst tool and the handoffs, review, dispatching apply, REPL, `chat`, `memory`, `reset`. First adjustment made through the coach.
3. **Check-in and follow-on.** `tri-coach check-in` with its refusal and exit codes, the `checkin` memory entry, the post-apply nutrition regeneration and second gate, the routing dataset, evaluators and `eval`. Root `README.md` gains the package row, run lines and a status entry.

## 14. Out of scope

`tri-wellness` (a fourth handoff added the same way once that package exists); multi-athlete; scheduled execution; any UI beyond the terminal; the coach editing change payloads directly; retiring the per-agent chats; writing to Garmin or TrainingPeaks by any path other than the packages' `apply_changes`.

## 15. Open items to verify in milestone 1

- That a `Command(graph=Command.PARENT)` emitted from a tool inside `create_agent` compiled with `checkpointer=False` reaches the coach `StateGraph` when the agent is invoked from a node function rather than added as a node directly. The `_retry.py` reading in §2 says it should; one graph test settles it. If not, the coach node is added as a subgraph node and `messages` are mapped explicitly.
- Whether the subgraph checkpoint namespace for the planning and nutrition nodes is renewed per superstep as expected, so a consultation never sees a previous consultation's state. The `main.py` reading in §2 says it is; one test with two consecutive consultations settles it.
- The exact stream event shapes for nested namespaces two levels deep (coach thread, planning node, its intake sub-agent) so the REPL labels them.
- That `tool.ainvoke(args)` on an adapter tool returns the server's text verbatim (not a content-block list) for both servers, so `ToolsCaller` can hand it to `parse_tool_text` unchanged.
