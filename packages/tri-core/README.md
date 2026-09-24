# tri-core

Shared code for the triathlon agents: `tri_core.config` (settings), `tri_core.mcp` (server specs
and a stdio MCP client), `tri_core.db` (connection, row models, repository), `tri_core.sync` (the
ETL behind `tri sync`), `tri_core.llm` (the model for each role, its effort and its Claude
fallbacks), `tri_core.harness` (the agent harness every package builds on), and
`tri_core.testing` (the `db` fixture, `ScriptedChatModel` and `StateSample`). See the READMEs
inside `src/tri_core/{mcp,db,sync}/`.

## Harness

| Module | What it holds |
|---|---|
| `harness.messages` | `text_of`, `last_ai_text` |
| `harness.agents` | `make_subagent` (no checkpointer; the parent graph owns the messages), `build_chat_agent` (a thread per conversation, in memory by default), `one_tool_call_at_a_time`. Every agent ends with `claude_fallback` (from `tri_core.llm`) and then prompt caching, which is always last. |
| `harness.agent_tool` | `agent_tool` and `Invocation`: an agent run on a throwaway thread, exposed as a one-question tool |
| `harness.handoff` | `handoff`, `turn_messages`, `undelivered`: leaving a sub-agent through `Command.PARENT` with a valid history |
| `harness.persistence` | `open_checkpointer(url, state_types)`, `open_store`, `checkpointer_ready`, `store_ready`, `make_serde`, `SETUP_HINT`, `STORE_SETUP_HINT` |
| `harness.turns` | `stream_turn`, `AgentTurnPrinter`, `GraphTurnPrinter`, `run_agent_turn`, `run_graph_turn`, `api_error_message`, `turn_config` |

Spec: `docs/superpowers/specs/2026-09-15-tri-harness-design.md`.
