# MCP Server

Ops Signals runs an MCP server over stdio, so an MCP client (an AI assistant or IDE) can read
findings, cases and analysis runs, and in write mode update cases.

## Running it

The server is part of the existing CLI:

```bash
./.venv/bin/python -m intelligence.cli mcp
./.venv/bin/python -m intelligence.cli mcp-write
```

- **`mcp`** (read-only): `health`, `services`, `service_metrics`, `findings`, `finding`, `cases`,
  `case`, `analysis_runs`, `analysis_run`, `similar_cases`, `memory_status`,
  `assistant_knowledge_status`.
- **`mcp-write`**: everything above, plus `create_case_from_finding`, `index_case_memory`,
  `update_investigation`, `update_rca`, `update_resolution`, and the chat and recommendation tools
  (`memory_chat`, `assistant_chat`, `analyzer_recommendation`, `question_answer`).

The tool list comes from `backend/app/api/mcp.py`; the read-only set is `_READ_ONLY_TOOLS` there.

## Testing it locally

```bash
./scripts/test_mcp.sh
MCP_MODE=mcp-write ./scripts/test_mcp.sh
```

The test script launches the stdio server and verifies `initialize` plus `tools/list`. It needs no
port; MCP runs over stdio only.

## Client configuration

```json
{
  "mcpServers": {
    "ops-signals": {
      "command": "python",
      "args": ["-m", "intelligence.cli", "mcp"],
      "cwd": "/path/to/ops-signals"
    }
  }
}
```

Use `mcp-write` instead of `mcp` if the client should be allowed to change cases and index memory.
