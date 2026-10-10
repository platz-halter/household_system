from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from household_service.models import (
    PointsSource,
    Recurrence,
    ReportPeriod,
    TakeoverStatus,
    TodoStatus,
)

# ---- Household users -------------------------------------------------


class HouseholdUserBrief(BaseModel):
    id: int
    subject: str
    display_name: str
    image_path: str | None
    model_config = {"from_attributes": True}


class HouseholdUserOut(HouseholdUserBrief):
    on_break: bool
    created_at: datetime
    # Only on the full Out shape, not HouseholdUserBrief — this is a
    # private preference of the account itself, not something relevant
    # to showing who else a todo/assignment belongs to.
    preferred_language: Literal["en", "de"]
    # The same cached role hint crud._is_eligible_for_tasks already
    # reads server-side (see HouseholdUser.role's own docstring) —
    # exposed here (not on HouseholdUserBrief) so a picker over the
    # full user list, like the Tasks page's pinned-owner select, can
    # exclude viewers client-side the same way the backend already
    # would reject one. Not secret: household members already know
    # each other's roles, same as the Admin panel's own group mapping.
    role: str | None = None


class HouseholdUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    on_break: bool | None = None


class HouseholdUserLanguageUpdate(BaseModel):
    preferred_language: Literal["en", "de"]


# ---- Categories ---------------------------------------------------------


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    icon: str | None = Field(default=None, max_length=50)


class CategoryOut(CategoryIn):
    id: int
    model_config = {"from_attributes": True}


# ---- Tasks ----------------------------------------------------------------


def _validate_weekdays(weekdays: list[int] | None) -> list[int] | None:
    if weekdays is None:
        return None
    if any(w < 0 or w > 6 for w in weekdays):
        raise ValueError("weekdays must be 0 (Monday) through 6 (Sunday)")
    return sorted(set(weekdays))


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points: int = Field(ge=0)
    active: bool = True
    recurrence: Recurrence = Recurrence.daily
    weekdays: list[int] | None = None
    times_per_day: int = Field(default=1, ge=1)
    ramp_up_enabled: bool = False
    ramp_up_bonus_points: int = Field(default=0, ge=0)
    category_ids: list[int] = Field(default_factory=list)
    # "Always assign to" owner — see Task.pinned_user_id's own docstring.
    # Admin-only to set (crud.create_task), same as changing it later.
    pinned_user_id: int | None = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v):
        return _validate_weekdays(v)

    @model_validator(mode="after")
    def _check_recurrence(self) -> "TaskCreate":
        if self.recurrence == Recurrence.weekly:
            if not self.weekdays:
                raise ValueError("a weekly task needs at least one weekday")
        else:
            self.weekdays = None  # only weekly carries a weekday list
        return self


class TaskUpdate(BaseModel):
    """All fields optional — PATCH semantics, only provided fields change.
    Cross-checking `recurrence` against `weekdays` needs the task's
    current state when only one of the two is in this particular PATCH,
    so that validation lives in crud.update_task instead of here.
    `pinned_user_id` needs the SAME "was it actually provided" distinction
    for a different reason — explicit `null` must clear an existing pin,
    while omitting the field must leave it alone, so crud.update_task
    reads `"pinned_user_id" in data.model_fields_set` rather than the
    `is not None` pattern every other field here uses (which can set a
    value but can never explicitly clear one back to null)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points: int | None = Field(default=None, ge=0)
    active: bool | None = None
    recurrence: Recurrence | None = None
    weekdays: list[int] | None = None
    times_per_day: int | None = Field(default=None, ge=1)
    ramp_up_enabled: bool | None = None
    ramp_up_bonus_points: int | None = Field(default=None, ge=0)
    category_ids: list[int] | None = None
    pinned_user_id: int | None = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v):
        return _validate_weekdays(v)


class TaskOut(BaseModel):
    id: int
    name: str
    description: str | None
    points: int
    active: bool
    recurrence: Recurrence
    weekdays: list[int] | None
    times_per_day: int
    ramp_up_enabled: bool
    ramp_up_bonus_points: int
    categories: list[CategoryOut]
    created_at: datetime
    updated_at: datetime
    # True if this task is reachable only as someone else's chain task
    # (see ChainLinkOut) — derived from task_chain_links, not a stored
    # column (see TaskChainLink's own docstring for why). A chain-child
    # task has exactly one source of instances (its parent's completion)
    # and can't be scheduled or completed on its own — the frontend uses
    # this to keep it out of the normal task list and the task picker
    # used when choosing a NEW chain link's child.
    is_chain_child: bool = False
    # "Always assign to" owner — see Task.pinned_user_id's own docstring.
    pinned_user_id: int | None = None
    pinned_user: HouseholdUserBrief | None = None
    # Who created this task — NULL for anything created before this
    # column existed. The frontend uses it to decide whether a non-admin
    # gets a Delete button on THIS task (see main.delete_task); nothing
    # else reads it.
    created_by_id: int | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, task, *, is_chain_child: bool = False) -> "TaskOut":
        return cls(
            id=task.id,
            name=task.name,
            description=task.description,
            points=task.points,
            active=task.active,
            recurrence=task.recurrence,
            weekdays=task.weekdays,
            times_per_day=task.times_per_day,
            ramp_up_enabled=task.ramp_up_enabled,
            ramp_up_bonus_points=task.ramp_up_bonus_points,
            categories=[CategoryOut.model_validate(c) for c in task.categories],
            created_at=task.created_at,
            updated_at=task.updated_at,
            is_chain_child=is_chain_child,
            pinned_user_id=task.pinned_user_id,
            pinned_user=(
                HouseholdUserBrief.model_validate(task.pinned_user)
                if task.pinned_user
                else None
            ),
            created_by_id=task.created_by_id,
        )


# ---- Chain tasks ---------------------------------------------------------


class ChainLinkIn(BaseModel):
    child_task_id: int
    same_user: bool = False


class ChainLinkOut(BaseModel):
    id: int
    parent_task_id: int
    child_task_id: int
    child_task_name: str
    same_user: bool
    position: int

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, link) -> "ChainLinkOut":
        return cls(
            id=link.id,
            parent_task_id=link.parent_task_id,
            child_task_id=link.child_task_id,
            child_task_name=link.child_task.name,
            same_user=link.same_user,
            position=link.position,
        )


class ChainParentOut(BaseModel):
    """The reverse of ChainLinkOut — which task(s) chain THIS one, for
    the "already chained, complete it directly anyway?" confirm (see
    TaskCompleteRequest.force)."""

    id: int
    parent_task_id: int
    parent_task_name: str
    same_user: bool

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, link) -> "ChainParentOut":
        return cls(
            id=link.id,
            parent_task_id=link.parent_task_id,
            parent_task_name=link.parent_task.name,
            same_user=link.same_user,
        )


class TodoStubOut(BaseModel):
    """Just enough to name a todo in a confirmation or a result summary
    — used for the event-group-run bulk delete's preview/result
    (EventGroupRunCleanup)."""

    id: int
    title: str

    model_config = {"from_attributes": True}


class EventGroupRunCleanup(BaseModel):
    """Shared shape for both the bulk-delete dry-run preview (GET) and
    the real result (POST) of deleting everything from one event group
    run — same crud computation backs both, so the two can't drift
    apart (see crud.event_group_run_delete_preview /
    delete_event_group_run_todos)."""

    to_delete: list[TodoStubOut]
    to_keep: list[TodoStubOut]


class ChainChildOut(BaseModel):
    """A still-open TodoItem that was pre-spawned at THIS todo's own
    creation (see crud._spawn_chain_children_on_creation) — used only to
    warn before cancelling: "this will also delete {these}" (crud.
    cancel_todo deletes them for real once confirmed). Deliberately
    thin — just enough to name them in a confirm dialog."""

    id: int
    title: str

    model_config = {"from_attributes": True}


class TaskCompleteRequest(BaseModel):
    """Optional override so an admin/user can log a completion on behalf of
    someone else; omit (or send an empty body) to log it for yourself."""

    household_user_id: int | None = None
    # Explicit, confirmed override for completing a chain-child task
    # directly (see crud.complete_task) — the frontend only ever sets
    # this after showing the user which task(s) chain it and asking.
    force: bool = False
    # A second, independent override — logs a completion past the
    # task's own times_per_day cap for today. The frontend only ever
    # sets this after showing how many times it's already been logged
    # today and confirming explicitly; kept separate from `force` so
    # a chain-child override can never silently also bypass this, or
    # vice versa (see crud.complete_task's own docstring).
    force_daily_cap: bool = False


# ---- Points ----------------------------------------------------------------


class PointsEntryOut(BaseModel):
    id: int
    household_user: HouseholdUserBrief
    points: int
    source: PointsSource
    task_id: int | None
    task_name: str | None
    todo_item_id: int | None
    todo_title: str | None
    earned_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, entry) -> "PointsEntryOut":
        return cls(
            id=entry.id,
            household_user=HouseholdUserBrief.model_validate(entry.household_user),
            points=entry.points,
            source=entry.source,
            task_id=entry.task_id,
            task_name=entry.task.name if entry.task else None,
            todo_item_id=entry.todo_item_id,
            todo_title=entry.todo_item.title if entry.todo_item else None,
            earned_at=entry.earned_at,
        )


class LeaderboardEntry(BaseModel):
    user: HouseholdUserBrief
    total_points: int


class ActivityDay(BaseModel):
    date: date
    points: int


# ---- Todo board -------------------------------------------------------


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points: int = Field(ge=0)
    due_in_days: int | None = Field(
        default=None, ge=0, description="0 = due today; omit for no due date"
    )
    assigned_to_id: int | None = None
    # Set when posting a todo prefilled "From task" — its chain children
    # (if any) now spawn immediately alongside this todo itself, rather
    # than waiting for completion (see crud._spawn_chain_children_on_
    # creation), the same as a task-sourced todo an event group created
    # (crud.trigger_event_group).
    source_task_id: int | None = None
    # Only consulted when source_task_id is also set. True (default)
    # spawns this task's chain children right away, same as an event
    # group's roots always do. False "deactivates" them for this one
    # todo specifically — the frontend only shows this as a checkbox
    # when the picked task actually has outgoing chain links to skip.
    spawn_chain_children: bool = True


class TodoReassignIn(BaseModel):
    """Admin-only: hand an open board item straight to someone else,
    no acceptance needed (see crud.reassign_todo). Distinct from a
    takeover request, which is consent-based."""

    assigned_to_id: int


class TodoUpdate(BaseModel):
    """PATCH semantics like TaskUpdate — a field left out is left alone.
    This means a due date, once set, can only be moved, not cleared; same
    limitation as the rest of this codebase's PATCH endpoints."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points: int | None = Field(default=None, ge=0)
    due_in_days: int | None = Field(default=None, ge=0)
    assigned_to_id: int | None = None


class TodoOut(BaseModel):
    id: int
    title: str
    description: str | None
    points: int
    due_date: date | None
    status: TodoStatus
    # None only for a scheduled Event Group's own auto-trigger — no human
    # actor at all for that (see crud.trigger_event_group). The frontend
    # shows "Scheduled" in place of "by {name}" when this is None.
    created_by: HouseholdUserBrief | None
    assigned_to: HouseholdUserBrief | None
    completed_by: HouseholdUserBrief | None
    completed_at: datetime | None
    created_at: datetime
    # Set only for a todo spawned by a chain task — the PARENT task's
    # name, for the frontend to show "After: {name}" instead of the
    # ordinary "From the board" label. None for a user-posted todo.
    chain_parent_task_name: str | None = None
    # Set only for a todo tagged with an event group run (either one of
    # the group's own root todos, or a chain descendant that inherited
    # the tag — see crud._spawn_chain_children) — lets the Board cluster
    # everything from the same triggering together and label it.
    event_group_run_id: int | None = None
    event_group_name: str | None = None
    event_group_triggered_at: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, todo) -> "TodoOut":
        return cls(
            id=todo.id,
            title=todo.title,
            description=todo.description,
            points=todo.points,
            due_date=todo.due_date,
            status=todo.status,
            created_by=(
                HouseholdUserBrief.model_validate(todo.created_by)
                if todo.created_by
                else None
            ),
            assigned_to=(
                HouseholdUserBrief.model_validate(todo.assigned_to)
                if todo.assigned_to
                else None
            ),
            completed_by=(
                HouseholdUserBrief.model_validate(todo.completed_by)
                if todo.completed_by
                else None
            ),
            completed_at=todo.completed_at,
            created_at=todo.created_at,
            chain_parent_task_name=(
                todo.chain_link.parent_task.name if todo.chain_link else None
            ),
            event_group_run_id=todo.event_group_run_id,
            event_group_name=(
                todo.event_group_run.event_group.name if todo.event_group_run else None
            ),
            event_group_triggered_at=(
                todo.event_group_run.triggered_at if todo.event_group_run else None
            ),
        )


# ---- Event groups ---------------------------------------------------------


class EventGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    root_task_ids: list[int] = Field(min_length=1)
    # Chain descendants of a root to leave untagged when they eventually
    # spawn — see EventGroupExclusion. Any id here that isn't actually a
    # descendant of one of the roots (or that duplicates a root) is just
    # ignored, not an error — the frontend only ever sends ids straight
    # from the live preview, so this is a defensive default rather than
    # a validation path that needs its own error message.
    excluded_task_ids: list[int] = Field(default_factory=list)
    # None = not scheduled (the only way to trigger it is the manual
    # button). "monthly" is deliberately not offered — see EventGroup's
    # own docstring for why. UTC, same convention as
    # HouseholdSettings.nudge_hour.
    schedule_recurrence: Literal["daily", "weekly"] | None = None
    schedule_weekdays: list[int] | None = None
    schedule_hour: int = Field(default=18, ge=0, le=23)

    @field_validator("schedule_weekdays")
    @classmethod
    def _check_schedule_weekdays(cls, v):
        return _validate_weekdays(v)

    @model_validator(mode="after")
    def _check_schedule_recurrence(self) -> "EventGroupIn":
        if self.schedule_recurrence == "weekly":
            if not self.schedule_weekdays:
                raise ValueError("a weekly schedule needs at least one weekday")
        else:
            self.schedule_weekdays = None
        return self


class EventGroupRootOut(BaseModel):
    task_id: int
    task_name: str
    points: int
    position: int


class EventGroupOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    roots: list[EventGroupRootOut]
    excluded_task_ids: list[int]
    schedule_recurrence: Literal["daily", "weekly"] | None
    schedule_weekdays: list[int] | None
    schedule_hour: int

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, group) -> "EventGroupOut":
        return cls(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            roots=[
                EventGroupRootOut(
                    task_id=r.task_id,
                    task_name=r.task.name,
                    points=r.task.points,
                    position=r.position,
                )
                for r in group.roots
            ],
            excluded_task_ids=[e.task_id for e in group.exclusions],
            schedule_recurrence=group.schedule_recurrence,
            schedule_weekdays=group.schedule_weekdays,
            schedule_hour=group.schedule_hour,
        )


class EventGroupPreviewRequest(BaseModel):
    root_task_ids: list[int] = Field(min_length=1)
    excluded_task_ids: list[int] = Field(default_factory=list)


class EventGroupPreviewItem(BaseModel):
    task_id: int
    task_name: str
    points: int
    is_root: bool
    # Which root spawns this — None for a root itself, the root's own
    # name for a chain descendant (so the frontend can show "After: X",
    # same label convention as TodoOut.chain_parent_task_name).
    parent_task_name: str | None = None
    excluded: bool = False


class EventGroupTriggerResult(BaseModel):
    run_id: int
    todos: list[TodoOut]


# ---- Task assignments / balancing tool ---------------------------------


class TaskAssignmentOut(BaseModel):
    id: int
    task_id: int
    task_name: str
    task_points: int
    household_user: HouseholdUserBrief
    period_start: date
    period_end: date

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, a) -> "TaskAssignmentOut":
        return cls(
            id=a.id,
            task_id=a.task_id,
            task_name=a.task.name,
            task_points=a.task.points,
            household_user=HouseholdUserBrief.model_validate(a.household_user),
            period_start=a.period_start,
            period_end=a.period_end,
        )


class BalancingUserSummary(BaseModel):
    household_user: HouseholdUserBrief
    new_task_count: int
    new_todo_count: int
    new_expected_points: int
    # The mid-week pull pass, separate from the counts above since it's a
    # reshuffle rather than new work: how many existing assignments this
    # user gained/lost this run, and the net point swing (positive if
    # they gained more value than they lost).
    reassigned_in_count: int = 0
    reassigned_out_count: int = 0
    reassigned_net_points: int = 0


class ReassignmentOut(BaseModel):
    """One task pulled from its holder and handed to someone else by the
    mid-week rebalance pass (household_service/balancing.rebalance)."""

    task_name: str
    points: int
    from_user: HouseholdUserBrief
    to_user: HouseholdUserBrief


class BalancingRunResult(BaseModel):
    week_period_start: date
    week_period_end: date
    month_period_start: date
    month_period_end: date
    task_assignments: list[TaskAssignmentOut]
    todo_assignments: list[TodoOut]
    reassignments: list[ReassignmentOut]
    unassigned_task_count: int
    unassigned_todo_count: int
    by_user: list[BalancingUserSummary]


# ---- Takeover requests ---------------------------------------------------


class TakeoverRequestIn(BaseModel):
    target_id: int


class TakeoverRequestOut(BaseModel):
    id: int
    requester: HouseholdUserBrief
    target: HouseholdUserBrief
    status: TakeoverStatus
    todo_item_id: int | None
    todo_title: str | None
    task_assignment_id: int | None
    task_name: str | None
    created_at: datetime
    responded_at: datetime | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, req) -> "TakeoverRequestOut":
        return cls(
            id=req.id,
            requester=HouseholdUserBrief.model_validate(req.requester),
            target=HouseholdUserBrief.model_validate(req.target),
            status=req.status,
            todo_item_id=req.todo_item_id,
            todo_title=req.todo_item.title if req.todo_item else None,
            task_assignment_id=req.task_assignment_id,
            task_name=req.task_assignment.task.name if req.task_assignment else None,
            created_at=req.created_at,
            responded_at=req.responded_at,
        )


# ---- Settings ---------------------------------------------------------


class HouseholdSettingsOut(BaseModel):
    weekly_points_goal: int | None
    points_to_money_rate: float | None
    currency: str
    nudge_weekday: int | None
    nudge_hour: int
    last_nudge_sent_week: str | None
    last_balance_run: date | None
    week_start_weekday: int
    auto_report_enabled: bool
    last_auto_report_period: date | None
    overdue_delete_after_days: int | None
    timezone: str
    default_language: Literal["en", "de"]
    model_config = {"from_attributes": True}


class HouseholdSettingsUpdate(BaseModel):
    weekly_points_goal: int | None = Field(default=None, ge=0)
    points_to_money_rate: float | None = Field(default=None, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    nudge_weekday: int | None = Field(default=None, ge=0, le=6)
    nudge_hour: int = Field(default=18, ge=0, le=23)
    week_start_weekday: int = Field(default=0, ge=0, le=6)
    auto_report_enabled: bool = False
    # None (default) = off. See HouseholdSettings' own docstring.
    overdue_delete_after_days: int | None = Field(default=None, ge=1)
    # IANA name — see HouseholdSettings' own docstring for exactly what
    # this does and doesn't affect.
    timezone: str = Field(default="UTC")
    # What a BRAND NEW HouseholdUser starts with — not retroactive. See
    # HouseholdSettings.default_language's own docstring.
    default_language: Literal["en", "de"] = "en"

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {v!r}") from exc
        return v


# ---- Reports -------------------------------------------------------------


class ReportCreate(BaseModel):
    period_type: ReportPeriod
    # Any date within the target week/month — the service resolves it to
    # that period's actual start/end (the admin-configured week start, or
    # the calendar month).
    period_date: date


class ReportOut(BaseModel):
    id: int
    period_type: ReportPeriod
    period_start: date
    period_end: date
    # Null for one the scheduler generated automatically.
    generated_by: HouseholdUserBrief | None
    created_at: datetime
    paid_at: datetime | None
    # Resolved server-side (against the CURRENT week_start_weekday) at
    # request time, not stored — whether this report's period is exactly
    # last week's, for the admin UI's "Last week" chip.
    is_last_week: bool = False

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, report, *, is_last_week: bool = False) -> "ReportOut":
        return cls(
            id=report.id,
            period_type=report.period_type,
            period_start=report.period_start,
            period_end=report.period_end,
            generated_by=HouseholdUserBrief.model_validate(report.generated_by)
            if report.generated_by
            else None,
            created_at=report.created_at,
            paid_at=report.paid_at,
            is_last_week=is_last_week,
        )


class ReportMarkPaidIn(BaseModel):
    paid: bool


# ---- Web Push --------------------------------------------------------------


class VapidPublicKeyOut(BaseModel):
    public_key: str | None


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    """Matches the shape of PushSubscription.toJSON() from the browser."""

    endpoint: str = Field(max_length=500)
    keys: PushSubscriptionKeys


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=500)


class NudgeResult(BaseModel):
    notified: int
    skipped_already_met_goal: int
    skipped_no_subscription: int


class TestPushResult(BaseModel):
    sent: int


# ---- Notification inbox -------------------------------------------------


class NotificationOut(BaseModel):
    id: int
    title: str
    body: str
    url: str
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}
