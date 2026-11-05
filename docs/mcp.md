# MCP (Model Context Protocol)

**Status: optional / stretch (F-26). Build only after the MVP works.**

Our own tool registry (agents.md) is simpler than MCP and is what the MVP uses. MCP only matters if outside tools should call this platform.

## Why
With an MCP server, AI coding tools (Claude Code, Cursor, Antigravity) could ask the platform **while generating code**: "which protections does this change touch?", "did my last edit break anything?"

## Approach
A thin MCP server wraps the existing REST API. No new logic.

| Tool | Maps to | Purpose |
|---|---|---|
| `list_protections(project)` | GET /projects/{id}/protections | What must not break |
| `check_change(project, diff)` | POST /versions/{id}/runs (monitor) | Run affected tests on a proposed change |
| `get_regressions(project)` | GET /projects/{id}/regressions | Open regressions |
| `get_matrix(project)` | GET /projects/{id}/matrix | Protection x version status |

## Rules
- Read-mostly: no tool merges, approves or deletes anything.
- Same auth and roles as the REST API.
- Results include evidence so the calling tool can fix its own change.
- Rate and budget limits like any other run.

## Honest note
Demo-friendly but not part of the research claim. Do it last. On a 16GB laptop, an extra server also costs RAM.
