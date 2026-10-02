from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from household_service.models import PointsSource, TodoStatus

# ---- Household users -------------------------------------------------


class HouseholdUserBrief(BaseModel):
    id: int
    subject: str
    display_name: str
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
    weekdays: list[int] | None = None
    times_per_day: int = Field(default=1, ge=1)
    ramp_up_enabled: bool = False
    ramp_up_bonus_points: int = Field(default=0, ge=0)
    category_ids: list[int] = Field(default_factory=list)

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, v):
        return _validate_weekdays(v)


class TaskUpdate(BaseModel):
    """All fields optional — PATCH semantics, only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    points: int | None = Field(default=None, ge=0)
    active: bool | None = None
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
    todo_item_id: int | None
    earned_at: datetime

    model_config = {"from_attributes": True}


class LeaderboardEntry(BaseModel):
    user: HouseholdUserBrief
    total_points: int


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


# ---- Settings ---------------------------------------------------------


class HouseholdSettingsOut(BaseModel):
    weekly_points_goal: int | None
    model_config = {"from_attributes": True}


class HouseholdSettingsUpdate(BaseModel):
    weekly_points_goal: int | None = Field(default=None, ge=0)
