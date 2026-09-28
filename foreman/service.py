from datetime import date, datetime, time, timedelta, timezone

from foreman.errors import ConflictError
from foreman.models import (
    SPRINT_LENGTH_DAYS,
    DailyDigest,
    Entry,
    EntryKind,
    Priority,
    Sprint,
    SprintOverview,
    SprintStatus,
    WorkItem,
    WorkKind,
    WorkStatus,
    new_id,
    utc_now,
)
from foreman.store import DynamoStore

ACTIVE_SPRINT_ALIAS = "active"
OVERVIEW_ENTRY_LIMIT = 30
DIGEST_ENTRY_LIMIT = 500


class ForemanService:
    def __init__(self, store: DynamoStore) -> None:
        self._store = store

    def create_sprint(self, name: str, goal: str, start_date: date) -> Sprint:
        sprint = Sprint(
            sprint_id=new_id("spr"),
            name=name,
            goal=goal,
            start_date=start_date,
            end_date=start_date + timedelta(days=SPRINT_LENGTH_DAYS - 1),
            status=SprintStatus.PLANNED,
            created_at=utc_now(),
        )
        self._store.put_sprint(sprint)
        return sprint

    def start_sprint(self, sprint_id: str) -> Sprint:
        sprint = self._store.get_sprint(sprint_id)
        if sprint.status == SprintStatus.CLOSED:
            raise ConflictError(f"sprint {sprint_id} is closed")
        if sprint.status == SprintStatus.ACTIVE:
            raise ConflictError(f"sprint {sprint_id} is already active")
        active = self._store.find_active_sprint()
        if active is not None:
            raise ConflictError(f"sprint {active.sprint_id} is already active")
        started = sprint.model_copy(update={"status": SprintStatus.ACTIVE})
        self._store.put_sprint(started)
        return started

    def close_sprint(self, sprint_id: str, retrospective: str | None) -> Sprint:
        sprint = self._store.get_sprint(sprint_id)
        if sprint.status != SprintStatus.ACTIVE:
            raise ConflictError(f"sprint {sprint_id} is {sprint.status}, only active can close")
        closed = sprint.model_copy(
            update={
                "status": SprintStatus.CLOSED,
                "closed_at": utc_now(),
                "retrospective": retrospective,
            }
        )
        self._store.put_sprint(closed)
        return closed

    def list_sprints(self) -> list[Sprint]:
        return self._store.list_sprints()

    def get_sprint(self, sprint_id: str) -> Sprint:
        return self._store.get_sprint(sprint_id)

    def find_active_sprint(self) -> Sprint | None:
        return self._store.find_active_sprint()

    def resolve_sprint_id(self, sprint_id: str | None) -> str:
        if sprint_id is None or sprint_id == ACTIVE_SPRINT_ALIAS:
            active = self.find_active_sprint()
            if active is None:
                raise ConflictError("no active sprint")
            return active.sprint_id
        return self._store.get_sprint(sprint_id).sprint_id

    def get_work_item(self, work_item_id: str) -> WorkItem:
        return self._store.get_work_item(work_item_id)

    def list_work_items(self, sprint_id: str | None) -> list[WorkItem]:
        return self._store.list_work_items(self.resolve_sprint_id(sprint_id))

    def add_work_item(
        self,
        title: str,
        kind: WorkKind,
        description: str,
        priority: Priority,
        ticket_key: str | None,
        repo: str | None,
        sprint_id: str | None,
        status: WorkStatus,
    ) -> WorkItem:
        resolved_sprint_id = self.resolve_sprint_id(sprint_id)
        sprint = self._store.get_sprint(resolved_sprint_id)
        if sprint.status == SprintStatus.CLOSED:
            raise ConflictError(f"sprint {resolved_sprint_id} is closed")
        now = utc_now()
        item = WorkItem(
            work_item_id=new_id("itm"),
            sprint_id=resolved_sprint_id,
            title=title,
            description=description,
            kind=kind,
            status=status,
            priority=priority,
            ticket_key=ticket_key,
            repo=repo,
            created_at=now,
            updated_at=now,
        )
        self._store.put_work_item(item)
        return item

    def update_work_item(
        self,
        work_item_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        status: WorkStatus | None = None,
        priority: Priority | None = None,
        ticket_key: str | None = None,
        repo: str | None = None,
        source: str,
    ) -> WorkItem:
        item = self._store.get_work_item(work_item_id)
        requested = {
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "ticket_key": ticket_key,
            "repo": repo,
        }
        changes = {field: value for field, value in requested.items() if value is not None}
        updated = WorkItem.model_validate({**item.model_dump(), **changes, "updated_at": utc_now()})
        self._store.put_work_item(updated)
        if status is not None and status != item.status:
            self._store.put_entry(
                Entry(
                    entry_id=new_id("ent"),
                    sprint_id=item.sprint_id,
                    work_item_id=work_item_id,
                    kind=EntryKind.STATUS_CHANGE,
                    body=f"{item.status} → {status}",
                    source=source,
                    created_at=utc_now(),
                )
            )
        return updated

    def add_entry(
        self,
        body: str,
        kind: EntryKind,
        work_item_id: str | None,
        sprint_id: str | None,
        source: str,
    ) -> Entry:
        if not body.strip():
            raise ValueError("entry body must not be empty")
        # An entry attached to an item always belongs to that item's sprint.
        if work_item_id is not None:
            resolved_sprint_id = self._store.get_work_item(work_item_id).sprint_id
        else:
            resolved_sprint_id = self.resolve_sprint_id(sprint_id)
        entry = Entry(
            entry_id=new_id("ent"),
            sprint_id=resolved_sprint_id,
            work_item_id=work_item_id,
            kind=kind,
            body=body,
            source=source,
            created_at=utc_now(),
        )
        self._store.put_entry(entry)
        return entry

    def list_sprint_entries(
        self, sprint_id: str | None, since: datetime | None, limit: int
    ) -> list[Entry]:
        return self._store.list_sprint_entries(
            self.resolve_sprint_id(sprint_id), since=since, until=None, limit=limit
        )

    def list_item_entries(self, work_item_id: str, limit: int) -> list[Entry]:
        return self._store.list_item_entries(work_item_id, limit)

    def get_sprint_overview(self, sprint_id: str | None) -> SprintOverview:
        sprint = self._store.get_sprint(self.resolve_sprint_id(sprint_id))
        items = self._store.list_work_items(sprint.sprint_id)
        counts = {status: 0 for status in WorkStatus}
        for item in items:
            counts[item.status] += 1
        elapsed_days = (utc_now().date() - sprint.start_date).days + 1
        return SprintOverview(
            sprint=sprint,
            items=items,
            recent_entries=self._store.list_sprint_entries(
                sprint.sprint_id, since=None, until=None, limit=OVERVIEW_ENTRY_LIMIT
            ),
            counts=counts,
            day_number=max(0, min(SPRINT_LENGTH_DAYS, elapsed_days)),
        )

    def get_daily_digest(self, sprint_id: str | None, day: date) -> DailyDigest:
        sprint = self._store.get_sprint(self.resolve_sprint_id(sprint_id))
        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        entries = self._store.list_sprint_entries(
            sprint.sprint_id,
            since=day_start,
            until=day_start + timedelta(days=1),
            limit=DIGEST_ENTRY_LIMIT,
        )
        chronological = list(reversed(entries))
        groups: list[tuple[WorkItem | None, list[Entry]]] = []
        sprint_level = [e for e in chronological if e.work_item_id is None]
        if sprint_level:
            groups.append((None, sprint_level))
        for item in self._store.list_work_items(sprint.sprint_id):
            item_entries = [e for e in chronological if e.work_item_id == item.work_item_id]
            if item_entries:
                groups.append((item, item_entries))
        return DailyDigest(sprint=sprint, day=day, entries_by_item=groups)
