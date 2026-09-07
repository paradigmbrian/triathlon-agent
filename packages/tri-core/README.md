# tri-core

Shared, model-free code for the triathlon agents: `tri_core.config` (settings), `tri_core.mcp`
(server specs and a stdio MCP client), `tri_core.db` (connection, row models, repository),
`tri_core.sync` (the ETL behind `tri sync`), and `tri_core.testing` (the `db` fixture and
`ScriptedChatModel`). See the READMEs inside `src/tri_core/{mcp,db,sync}/`.
