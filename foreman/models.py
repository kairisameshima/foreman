import re
import uuid
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, field_validator

SPRINT_LENGTH_DAYS = 14
TICKET_KEY_PATTERN = re.compile(r"^[A-Z]+-\d+$")


def iso_timestamp(value: datetime) -> str:
    """Fixed-width UTC ISO 8601, so lexical order of stored strings equals time order."""
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


UtcDatetime = Annotated[AwareDatetime, PlainSerializer(iso_timestamp, when_used="json")]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SprintStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    CLOSED = "closed"


class WorkKind(StrEnum):
    PLANNED = "planned"
    UNPLANNED = "unplanned"


class WorkStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    DROPPED = "dropped"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EntryKind(StrEnum):
    UPDATE = "update"
    LOG = "log"
    CONTEXT = "context"
    BLOCKER = "blocker"
    DECISION = "decision"
    STATUS_CHANGE = "status_change"


class Sprint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sprint_id: str
    name: str = Field(min_length=1)
    goal: str
    start_date: date
    end_date: date
    status: SprintStatus
    created_at: UtcDatetime
    closed_at: UtcDatetime | None = None
    retrospective: str | None = None


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    work_item_id: str
    sprint_id: str
    title: str = Field(min_length=1)
    description: str
    kind: WorkKind
    status: WorkStatus
    priority: Priority
    ticket_key: str | None = None
    repo: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @field_validator("ticket_key", mode="before")
    @classmethod
    def normalize_ticket_key(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if not TICKET_KEY_PATTERN.match(normalized):
            raise ValueError(f"ticket_key must look like DEV-82, got {value!r}")
        return normalized


class Entry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entry_id: str
    sprint_id: str
    work_item_id: str | None
    kind: EntryKind
    body: str = Field(min_length=1)
    source: str
    created_at: UtcDatetime


class SprintOverview(BaseModel):
    sprint: Sprint
    items: list[WorkItem]
    recent_entries: list[Entry]
    counts: dict[WorkStatus, int]
    day_number: int


class DailyDigest(BaseModel):
    sprint: Sprint
    day: date
    entries_by_item: list[tuple[WorkItem | None, list[Entry]]]
