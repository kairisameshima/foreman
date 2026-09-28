from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from foreman.config import settings
from foreman.models import (
    Entry,
    EntryKind,
    Priority,
    SprintStatus,
    WorkItem,
    WorkKind,
    WorkStatus,
    utc_now,
)
from foreman.service import ForemanService

PACKAGE_DIR = Path(__file__).parent
UI_SOURCE = "ui"
ITEM_ENTRY_LIMIT = 100
STATUS_CHANGED_EVENT = "item-status-changed"
UI_ENTRY_KINDS = [kind for kind in EntryKind if kind != EntryKind.STATUS_CHANGE]

router = APIRouter()
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

_service: ForemanService | None = None


def configure(service: ForemanService) -> None:
    global _service
    _service = service


def _require_service() -> ForemanService:
    if _service is None:
        raise RuntimeError("web.configure() must be called before serving requests")
    return _service


def ticket_url(ticket_key: str) -> str:
    return settings.ticket_url_template.format(ticket_key=ticket_key)


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC")


templates.env.filters["ticket_url"] = ticket_url
templates.env.filters["timestamp"] = format_timestamp
templates.env.globals["work_statuses"] = list(WorkStatus)
templates.env.globals["work_kinds"] = list(WorkKind)
templates.env.globals["priorities"] = list(Priority)
templates.env.globals["entry_kinds"] = UI_ENTRY_KINDS


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def render_error(request: Request, status_code: int, message: str) -> HTMLResponse:
    response = templates.TemplateResponse(
        request, "error.html", {"message": message, "status_code": status_code}, status_code
    )
    # htmx fragment requests would otherwise swap the error into a card or list.
    if request.headers.get("HX-Request"):
        response.headers["HX-Retarget"] = "body"
        response.headers["HX-Reswap"] = "innerHTML"
    return response


def _sprint_entry_list_context(sprint_id: str) -> dict[str, object]:
    overview = _require_service().get_sprint_overview(sprint_id)
    return {
        "entries": overview.recent_entries,
        "item_titles": {item.work_item_id: item.title for item in overview.items},
    }


def _item_entry_list_context(item: WorkItem) -> dict[str, object]:
    entries: list[Entry] = _require_service().list_item_entries(item.work_item_id, ITEM_ENTRY_LIMIT)
    return {"entries": entries, "item_titles": {item.work_item_id: item.title}}


def _render_dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"sprints": _require_service().list_sprints(), "today": utc_now().date()},
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/", response_model=None)
def index(request: Request) -> Response:
    active = _require_service().find_active_sprint()
    if active is not None:
        return _see_other(f"/sprints/{active.sprint_id}")
    return _render_dashboard(request)


@router.get("/sprints")
def sprint_list(request: Request) -> HTMLResponse:
    return _render_dashboard(request)


@router.post("/sprints")
def create_sprint(
    name: Annotated[str, Form()],
    start_date: Annotated[date, Form()],
    goal: Annotated[str, Form()] = "",
) -> RedirectResponse:
    sprint = _require_service().create_sprint(name, goal, start_date)
    return _see_other(f"/sprints/{sprint.sprint_id}")


@router.get("/sprints/{sprint_id}")
def sprint_page(request: Request, sprint_id: str) -> HTMLResponse:
    overview = _require_service().get_sprint_overview(sprint_id)
    columns = [
        (status, [item for item in overview.items if item.status == status])
        for status in WorkStatus
    ]
    return templates.TemplateResponse(
        request,
        "sprint.html",
        {
            "overview": overview,
            "sprint": overview.sprint,
            "columns": columns,
            "entries": overview.recent_entries,
            "item_titles": {item.work_item_id: item.title for item in overview.items},
            "today": utc_now().date(),
            "is_open": overview.sprint.status != SprintStatus.CLOSED,
        },
    )


@router.post("/sprints/{sprint_id}/start")
def start_sprint(sprint_id: str) -> RedirectResponse:
    _require_service().start_sprint(sprint_id)
    return _see_other(f"/sprints/{sprint_id}")


@router.post("/sprints/{sprint_id}/close")
def close_sprint(sprint_id: str, retrospective: Annotated[str, Form()] = "") -> RedirectResponse:
    _require_service().close_sprint(sprint_id, _blank_to_none(retrospective))
    return _see_other(f"/sprints/{sprint_id}")


@router.get("/sprints/{sprint_id}/day")
def jump_to_day(sprint_id: str, day: date) -> RedirectResponse:
    return _see_other(f"/sprints/{sprint_id}/day/{day.isoformat()}")


@router.get("/sprints/{sprint_id}/day/{day}")
def day_page(request: Request, sprint_id: str, day: date) -> HTMLResponse:
    digest = _require_service().get_daily_digest(sprint_id, day)
    return templates.TemplateResponse(
        request,
        "day.html",
        {
            "digest": digest,
            "sprint": digest.sprint,
            "previous_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
        },
    )


@router.post("/items")
def create_item(
    sprint_id: Annotated[str, Form()],
    title: Annotated[str, Form()],
    kind: Annotated[WorkKind, Form()],
    priority: Annotated[Priority, Form()] = Priority.MEDIUM,
    ticket_key: Annotated[str, Form()] = "",
    repo: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    item = _require_service().add_work_item(
        title=title,
        kind=kind,
        description=description,
        priority=priority,
        ticket_key=_blank_to_none(ticket_key),
        repo=_blank_to_none(repo),
        sprint_id=sprint_id,
        status=WorkStatus.TODO,
    )
    return _see_other(f"/sprints/{item.sprint_id}")


@router.get("/items/{work_item_id}")
def item_page(request: Request, work_item_id: str) -> HTMLResponse:
    service = _require_service()
    item = service.get_work_item(work_item_id)
    sprint = service.get_sprint(item.sprint_id)
    return templates.TemplateResponse(
        request,
        "item.html",
        {"item": item, "sprint": sprint, **_item_entry_list_context(item)},
    )


@router.post("/items/{work_item_id}/status")
def update_item_status(
    request: Request, work_item_id: str, status: Annotated[WorkStatus, Form()]
) -> HTMLResponse:
    item = _require_service().update_work_item(work_item_id, status=status, source=UI_SOURCE)
    response = templates.TemplateResponse(request, "partials/item_card.html", {"item": item})
    # The sprint board listens for this event and re-renders so the card moves column.
    response.headers["HX-Trigger"] = STATUS_CHANGED_EVENT
    return response


@router.post("/entries")
def create_entry(
    request: Request,
    body: Annotated[str, Form()],
    kind: Annotated[EntryKind, Form()],
    sprint_id: Annotated[str, Form()],
    work_item_id: Annotated[str, Form()] = "",
) -> HTMLResponse:
    service = _require_service()
    item_id = _blank_to_none(work_item_id)
    entry = service.add_entry(
        body=body, kind=kind, work_item_id=item_id, sprint_id=sprint_id, source=UI_SOURCE
    )
    if item_id is not None:
        context = _item_entry_list_context(service.get_work_item(item_id))
    else:
        context = _sprint_entry_list_context(entry.sprint_id)
    return templates.TemplateResponse(request, "partials/entry_list.html", context)
