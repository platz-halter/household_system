from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from household_service.models import PointsSource, Recurrence, ReportPeriod, TodoStatus

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


class HouseholdUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    on_break: bool | None = None


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
            self.weekdays = None  # daily/monthly never carry a weekday list
        return self


class TaskUpdate(BaseModel):
    """All fields optional — PATCH semantics, only provided fields change.
    Cross-checking `recurrence` against `weekdays` needs the task's
    current state when only one of the two is in this particular PATCH,
    so that validation lives in crud.update_task instead of here."""

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

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, task) -> "TaskOut":
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
        )


class TaskCompleteRequest(BaseModel):
    """Optional override so an admin/user can log a completion on behalf of
    someone else; omit (or send an empty body) to log it for yourself."""

    household_user_id: int | None = None


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
    created_by: HouseholdUserBrief
    assigned_to: HouseholdUserBrief | None
    completed_by: HouseholdUserBrief | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


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
    model_config = {"from_attributes": True}


class HouseholdSettingsUpdate(BaseModel):
    weekly_points_goal: int | None = Field(default=None, ge=0)
    points_to_money_rate: float | None = Field(default=None, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    nudge_weekday: int | None = Field(default=None, ge=0, le=6)
    nudge_hour: int = Field(default=18, ge=0, le=23)
    week_start_weekday: int = Field(default=0, ge=0, le=6)
    auto_report_enabled: bool = False

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        return v.strip().upper()


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
