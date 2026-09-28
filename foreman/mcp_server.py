from datetime import date, datetime, timezone
from typing import Literal

from mcp.server.fastmcp import FastMCP

from foreman.models import (
    DailyDigest,
    Entry,
    EntryKind,
    Priority,
    Sprint,
    SprintOverview,
    WorkItem,
    WorkKind,
    WorkStatus,
    utc_now,
)
from foreman.service import ForemanService

WorkKindName = Literal["planned", "unplanned"]
PriorityName = Literal["low", "medium", "high"]
WorkStatusName = Literal["todo", "in_progress", "blocked", "done", "dropped"]
AgentEntryKindName = Literal["update", "log", "context", "blocker", "decision"]

mcp = FastMCP("foreman", stateless_http=True, json_response=True)

_service: ForemanService | None = None


def configure(service: ForemanService) -> None:
    global _service
    _service = service


def _require_service() -> ForemanService:
    if _service is None:
        raise RuntimeError("mcp_server.configure() must be called before serving tools")
    return _service


def _parse_since(since: str | None) -> datetime | None:
    if since is None:
        return None
    parsed = datetime.fromisoformat(since)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@mcp.tool()
def create_sprint(name: str, goal: str = "", start_date: str | None = None) -> Sprint:
    """Create a planned 2-week sprint. start_date is YYYY-MM-DD and defaults to today (UTC)."""
    start = date.fromisoformat(start_date) if start_date else utc_now().date()
    return _require_service().create_sprint(name, goal, start)


@mcp.tool()
def start_sprint(sprint_id: str) -> Sprint:
    """Make a planned sprint the active one. Fails if another sprint is already active."""
    return _require_service().start_sprint(sprint_id)


@mcp.tool()
def close_sprint(sprint_id: str, retrospective: str | None = None) -> Sprint:
    """Close the active sprint, optionally recording a retrospective."""
    return _require_service().close_sprint(sprint_id, retrospective)


@mcp.tool()
def list_sprints() -> list[Sprint]:
    """List all sprints, newest start date first."""
    return _require_service().list_sprints()


@mcp.tool()
def get_sprint(sprint_id: str = "active") -> SprintOverview:
    """Load a sprint with its work items, status counts, and recent entries.
    Call this first in a session to pick up context from earlier sessions."""
    return _require_service().get_sprint_overview(sprint_id)


@mcp.tool()
def add_work_item(
    title: str,
    kind: WorkKindName,
    description: str = "",
    priority: PriorityName = "medium",
    ticket_key: str | None = None,
    repo: str | None = None,
    sprint_id: str = "active",
    status: WorkStatusName = "todo",
) -> WorkItem:
    """Add a work item to a sprint. Use kind="unplanned" for work that arrived mid-sprint.
    ticket_key is an optional Linear/Jira key such as DEV-82."""
    return _require_service().add_work_item(
        title=title,
        kind=WorkKind(kind),
        description=description,
        priority=Priority(priority),
        ticket_key=ticket_key,
        repo=repo,
        sprint_id=sprint_id,
        status=WorkStatus(status),
    )


@mcp.tool()
def update_work_item(
    work_item_id: str,
    status: WorkStatusName | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: PriorityName | None = None,
    ticket_key: str | None = None,
    repo: str | None = None,
    source: str = "agent",
) -> WorkItem:
    """Change fields on a work item. Status changes are recorded on the timeline automatically."""
    return _require_service().update_work_item(
        work_item_id,
        title=title,
        description=description,
        status=WorkStatus(status) if status else None,
        priority=Priority(priority) if priority else None,
        ticket_key=ticket_key,
        repo=repo,
        source=source,
    )


@mcp.tool()
def list_work_items(
    sprint_id: str = "active",
    status: WorkStatusName | None = None,
    kind: WorkKindName | None = None,
) -> list[WorkItem]:
    """List a sprint's work items, optionally filtered by status and kind."""
    items = _require_service().list_work_items(sprint_id)
    return [
        item
        for item in items
        if (status is None or item.status == status) and (kind is None or item.kind == kind)
    ]


@mcp.tool()
def add_entry(
    body: str,
    kind: AgentEntryKindName = "update",
    work_item_id: str | None = None,
    sprint_id: str = "active",
    source: str = "agent",
) -> Entry:
    """Record progress, a log, context, a blocker, or a decision as markdown. Attach it to a
    work item when it concerns one; otherwise it is a sprint-level note."""
    return _require_service().add_entry(
        body=body,
        kind=EntryKind(kind),
        work_item_id=work_item_id,
        sprint_id=sprint_id,
        source=source,
    )


@mcp.tool()
def list_entries(
    sprint_id: str = "active",
    work_item_id: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[Entry]:
    """List timeline entries newest first, for a whole sprint or one work item.
    since is an ISO datetime and applies to sprint listings only."""
    service = _require_service()
    if work_item_id is not None:
        return service.list_item_entries(work_item_id, limit)
    return service.list_sprint_entries(sprint_id, _parse_since(since), limit)


@mcp.tool()
def get_daily_digest(day: str | None = None, sprint_id: str = "active") -> DailyDigest:
    """Summarize one day's entries grouped by work item. day is YYYY-MM-DD, default today (UTC)."""
    digest_day = date.fromisoformat(day) if day else utc_now().date()
    return _require_service().get_daily_digest(sprint_id, digest_day)
