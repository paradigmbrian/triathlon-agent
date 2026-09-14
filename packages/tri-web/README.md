# tri-web

A local web UI over the head coach. The server (`tri_web`, FastAPI on 127.0.0.1:8321) opens the coach graph the way `tri-coach chat` does: the same thread `coach`, the same Postgres checkpointer and store, so the terminal and the browser see one conversation and one memory. The React app lives in `web/` (plan 3).

Spec: `docs/superpowers/specs/2026-09-14-tri-web-design.md`.

## Run

```
uv run tri-web serve [--no-live] [--port 8321]   # the API only for now; plan 2 adds web/dist
uv run tri-web openapi > web/openapi.json        # the document web/src/api/types.ts is generated from
```

Startup takes 10 to 20 s while the MCP servers launch; `--no-live` skips them and `GET /api/system/status` reports `live: false`. Readiness failures print the CLI's hints and exit 2.

## Routes (all under `/api`)

| Route | Body | Returns |
|---|---|---|
| `GET /coach/thread` | | `ThreadView`: messages, `paused`, `held`, `stuck`, `running` |
| `POST /coach/turns` | `{text}` | SSE `TurnEvent`s; `409 {running}` when busy |
| `POST /coach/review` | `{action, note?, proposals?}` | SSE; `409 {reason: "no_review"}`; `422 {detail: "edit rejected", errors}` |
| `GET /coach/review/schema` | | `{proposal, planning_change, nutrition_change}` JSON schemas |
| `POST /coach/review/validate` | `{proposals}` or `{yaml}` | `{ok, proposals, errors: [{loc, msg}]}` |
| `GET /coach/review/yaml` | | `{yaml}` of the paused proposals |
| `GET /system/status` | | `{live, tools, ready: {api_key, checkpointer, store}, thread, running}` |

Events: `token {where, text}`, `tool_call {where, name, args}`, `tool_result {where, name, chars}`, `consult {domain, text}`, `report {text}`, `interrupt {narration, proposals}`, `error {message}`, `done {final_text, paused}`. `where` is `coach`, `planning`, `nutrition` or `analyst`.

One lock: a second turn, review, check-in or reset while one runs is refused with 409. A run continues after the browser disconnects; the lock releases when it finishes.

## Layout

```
src/tri_web/config.py    WebSettings (host, port, dist)
src/tri_web/runtime.py   Runtime, open_runtime
src/tri_web/events.py    TurnEmitter, start_turn, SSE framing
src/tri_web/thread.py    UiMessage, ThreadView, thread_snapshot
src/tri_web/review.py    schema, validate_json, validate_yaml, to_yaml
src/tri_web/schemas.py   request/response models, NoReview, EditRejected
src/tri_web/app.py       create_app
src/tri_web/routes/      coach.py, system.py
src/tri_web/cli.py       serve, openapi
```

## Tests

`uv run pytest packages/tri-web` (db tests skip when Postgres is down). Route tests run the graph over scripted models and an in-memory checkpointer through `httpx.ASGITransport`; no Anthropic call, no MCP server.
