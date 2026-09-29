# Foreman

Local sprint manager for agents. Agents record sprints, planned and unplanned work items, and timestamped entries (updates, logs, context, blockers, decisions) through an MCP server, so progress survives across sessions. A small web UI shows everything and allows minimal edits.

One FastAPI process serves both the MCP endpoint and the UI. Data lives in DynamoDB Local on a named Docker volume.

## Install

Requires Docker with Compose.

1. Start the server:

   ```bash
   git clone https://github.com/kairisameshima/foreman.git
   cd foreman
   docker compose up --build -d
   ```

2. Check that it is running:

   ```bash
   curl http://localhost:8765/health
   ```

   Expected output: `{"status":"ok"}`

3. Register the MCP server with your agent (see below).

Endpoints:

- UI: http://localhost:8765/
- MCP endpoint (Streamable HTTP): http://localhost:8765/mcp
- DynamoDB Local on the host: http://localhost:8001 (for `aws dynamodb ... --endpoint-url`)

The table is created on first start. The containers restart automatically with Docker.

## Register with agents

The MCP endpoint is a plain HTTP server, so no command or package is installed on the agent side. Each agent only needs the URL `http://localhost:8765/mcp`. If you change the published port in `docker-compose.yml`, change the URL to match.

### Claude Code

User scope, available in every project:

```bash
claude mcp add --transport http --scope user foreman http://localhost:8765/mcp
```

Verify with `claude mcp list`.

To share it with a team instead, put this in a project `.mcp.json`:

```json
{
  "mcpServers": {
    "foreman": { "type": "http", "url": "http://localhost:8765/mcp" }
  }
}
```

### Codex

```bash
codex mcp add foreman --url http://localhost:8765/mcp
```

Verify with `codex mcp list`.

Equivalent entry in `~/.codex/config.toml` (or a project `.codex/config.toml`):

```toml
[mcp_servers.foreman]
url = "http://localhost:8765/mcp"
```

### omp

omp does not need its own entry if you already registered Foreman with Claude Code or Codex. It imports servers from `~/.claude.json`, project `.mcp.json`, and `~/.codex/config.toml`.

To register it with omp directly, run `/mcp add` inside omp and choose the HTTP transport with the URL above. Or add it to `~/.omp/agent/mcp.json` (all projects) or `.omp/mcp.json` (one project):

```json
{
  "mcpServers": {
    "foreman": { "type": "http", "url": "http://localhost:8765/mcp" }
  }
}
```

Run `/mcp reload` in a running session, then `/mcp list` to verify. Tools are named `mcp__foreman_<tool>`.

## Tools

| Tool | Purpose |
|---|---|
| `create_sprint` | Create a planned 2-week sprint (start date defaults to today). |
| `start_sprint` | Make a planned sprint active. Only one sprint can be active. |
| `close_sprint` | Close the active sprint with an optional retrospective. |
| `list_sprints` | All sprints, newest first. |
| `get_sprint` | Sprint with work items, status counts, recent entries. Defaults to the active sprint. |
| `add_work_item` | Add a `planned` or `unplanned` item, optional `ticket_key` such as `DEV-82`. |
| `update_work_item` | Change status or other fields. Status changes are logged to the timeline. |
| `list_work_items` | Items in a sprint, filter by status or kind. |
| `add_entry` | Record an update, log, context, blocker, or decision, attached to an item or the sprint. |
| `list_entries` | Timeline for a sprint or one item, newest first. |
| `get_daily_digest` | One day's entries grouped by item. |

Every `sprint_id` parameter accepts `"active"` (the default) for the current sprint.

## Suggested agent workflow

1. Call `get_sprint` at the start of a session to load current items and recent entries.
2. Call `add_entry` as work progresses, attached to the relevant `work_item_id`.
3. Call `update_work_item` when an item changes status. Use `add_work_item` with `kind="unplanned"` for work that was not planned.

Pass a `source` label (for example the repo or session name) so the timeline shows who wrote each entry.

## Local development

```bash
poetry install
docker compose up -d dynamodb
DYNAMODB_ENDPOINT=http://localhost:8001 AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local \
  AWS_DEFAULT_REGION=local poetry run uvicorn foreman.app:app --port 8765 --reload
```

Stop the `foreman` container first (`docker compose stop foreman`) so port 8765 is free.

Checks:

```bash
poetry run black --check . --line-length 100
poetry run flake8
poetry run mypy foreman
```

## Configuration

| Env var | Default |
|---|---|
| `DYNAMODB_ENDPOINT` | `http://localhost:8000` |
| `FOREMAN_TABLE` | `foreman` |
| `PORT` | `8765` |
| `TICKET_URL_TEMPLATE` | `https://linear.app/farsight-ai/issue/{ticket_key}` |

## Reset data

```bash
docker compose down -v
```
