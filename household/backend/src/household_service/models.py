"""Household service tables: users, categories, tasks, points ledger, and
the one-off todo board.

When you add/change models here, generate the migration with:
    alembic -c household/backend/alembic.ini revision --autogenerate -m "..."
(see MIGRATIONS.md in the repo root).
"""

import enum
from datetime import date, datetime

from shared.db import Base
from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class TodoStatus(str, enum.Enum):
    open = "open"
    completed = "completed"
    cancelled = "cancelled"


class PointsSource(str, enum.Enum):
    task = "task"
    todo = "todo"


class Recurrence(str, enum.Enum):
    """How a Task repeats. Only `weekly` and `monthly` tasks are eligible
    for the balancing tool (household_service/balancing.py) — a `daily`
    task is a standing chore everyone's expected to do on their own, not
    something that makes sense to hand to one person for a whole period."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class HouseholdUser(Base):
    """Local profile for an authenticated subject (local-account username,
    or an Authentik preferred_username). This service doesn't own accounts
    — auth does — so there's no signup here; a row is created the first
    time a subject is seen (see crud.get_or_create_household_user)."""

    __tablename__ = "household_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    on_break: Mapped[bool] = mapped_column(Boolean, default=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # A cached hint of this subject's role, synced from the JWT on every
    # request that calls main._self (so practically every page load) —
    # NEVER the source of truth for authorization (that's always the
    # token itself, per-request, same as everywhere else in this app).
    # The only thing this is for is deciding who gets a push notification
    # about something admin-only (new reports) without needing a live
    # token to check against at send time.
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


task_categories = Table(
    "task_categories",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)

    tasks: Mapped[list["Task"]] = relationship(
        secondary=task_categories, back_populates="categories"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    points: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # How this task repeats. `weekly` tasks also set `weekdays` (which
    # weekdays, 0=Monday..6=Sunday); `daily` and `monthly` tasks leave it
    # null (daily = every day; monthly has no specific weekday). Only
    # `weekly`/`monthly` tasks are candidates for the balancing tool.
    recurrence: Mapped[Recurrence] = mapped_column(
        Enum(Recurrence, name="task_recurrence"),
        default=Recurrence.daily,
        server_default="daily",
    )
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    times_per_day: Mapped[int] = mapped_column(Integer, default=1)

    # "Ramp-up": bonus points awarded when the same person has exclusively
    # been the one completing this task so far (see crud.complete_task).
    ramp_up_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ramp_up_bonus_points: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    categories: Mapped[list[Category]] = relationship(
        secondary=task_categories, back_populates="tasks"
    )


class TaskAssignment(Base):
    """One recurring task handed to one person for one period, produced by
    the balancing tool (household_service/balancing.py). `period_start`/
    `period_end` are that week's Monday-Sunday (for a `weekly` task) or
    that month's 1st-last day (for `monthly`) — the unique constraint
    means re-running the balancer mid-period can't double-assign the same
    task. There's no explicit "completed" flag: whether it's done is
    derived from a PointsEntry existing for this task/user/period, same
    as every other task completion."""

    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "period_start", name="uq_task_assignment_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    household_user_id: Mapped[int] = mapped_column(
        ForeignKey("household_users.id", ondelete="CASCADE")
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when the mid-week rebalance pass (household_service/balancing.py
    # — rebalance()) pulls this assignment away from its original holder.
    # Null means "never pulled yet this period" — once set, this
    # assignment can't be pulled again (see rebalance()'s docstring for
    # why: without a one-pull-per-period limit, small day-to-day point
    # swings could bounce the same task back and forth indefinitely).
    reassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    task: Mapped[Task] = relationship()
    household_user: Mapped[HouseholdUser] = relationship()


class TodoItem(Base):
    """A one-off task request posted to the todo board, separate from the
    recurring `Task` schedule."""

    __tablename__ = "todo_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    points: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[TodoStatus] = mapped_column(
        Enum(TodoStatus, name="todo_status"), default=TodoStatus.open
    )

    created_by_id: Mapped[int] = mapped_column(ForeignKey("household_users.id"))
    # Who it was requested of, if anyone in particular (drives the push
    # notification once that's built) — any user/admin can still complete
    # it, this is metadata rather than an access restriction.
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("household_users.id"), nullable=True
    )
    completed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("household_users.id"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    created_by: Mapped[HouseholdUser] = relationship(foreign_keys=[created_by_id])
    assigned_to: Mapped[HouseholdUser | None] = relationship(
        foreign_keys=[assigned_to_id]
    )
    completed_by: Mapped[HouseholdUser | None] = relationship(
        foreign_keys=[completed_by_id]
    )


class PointsEntry(Base):
    """Ledger of every point award, from either a recurring-task completion
    or a completed todo item. The leaderboard and activity feed just sum/
    list this table, so both sources behave identically downstream."""

    __tablename__ = "points_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_user_id: Mapped[int] = mapped_column(ForeignKey("household_users.id"))
    points: Mapped[int] = mapped_column(Integer)
    source: Mapped[PointsSource] = mapped_column(
        Enum(PointsSource, name="points_source")
    )

    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    todo_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("todo_items.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    household_user: Mapped[HouseholdUser] = relationship()
    task: Mapped[Task | None] = relationship()
    todo_item: Mapped[TodoItem | None] = relationship()


class HouseholdSettings(Base):
    """Singleton config row — id is always 1."""

    __tablename__ = "household_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    weekly_points_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Money per point — display/reference only, no connection to an actual
    # payout process (see PROJECT_SPEC.md "Admin tools"). `currency` is an
    # ISO 4217 code (e.g. "EUR", "USD"); admin-selectable in the Admin panel.
    points_to_money_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")

    # Automatic weekly reminder schedule (see household_service/scheduler.py).
    # nudge_weekday is None by default — the feature is opt-in; the manual
    # "send now" button in the Admin panel works regardless of this.
    nudge_weekday: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0=Mon..6=Sun
    nudge_hour: Mapped[int] = mapped_column(Integer, default=18)  # 0-23, UTC
    # Bookkeeping so the scheduled job and the manual button don't double-
    # send in the same ISO week — "2026-W41" style, not admin-editable.
    last_nudge_sent_week: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Same idempotency pattern as last_nudge_sent_week, for the automatic
    # balancing run (household_service/scheduler.py) — now a daily job
    # (not just Monday/the 1st), since the mid-week rebalance pass needs
    # to re-check for imbalances more often than once a period. Not
    # admin-editable.
    last_balance_run: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Which weekday a "week" starts on for every weekly computation in the
    # app (points-this-week, the leaderboard's This/Last week filters, the
    # heatmap, the balancer's weekly period, auto-generated weekly
    # reports) — 0=Monday..6=Sunday, same convention as Task.weekdays.
    # Admin-editable; defaults to the Monday-start behavior this app
    # always had before this was configurable.
    week_start_weekday: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    # Auto-generates a report for the week that just ended, the first
    # time the scheduler notices it's over (see
    # crud.run_scheduled_auto_report_if_due) — off by default, same
    # opt-in pattern as the nudge schedule. last_auto_report_period is
    # that week's start date ("2026-09-28"), not admin-editable — it's
    # a "catch up" check (did THIS week get its report yet), not a
    # weekday/hour match, so it still fires correctly even if the
    # server was down right when the week rolled over.
    auto_report_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    last_auto_report_period: Mapped[date | None] = mapped_column(Date, nullable=True)


class ReportPeriod(str, enum.Enum):
    week = "week"
    month = "month"


class Report(Base):
    """A generated PDF points report, kept on disk so past reports stay
    downloadable rather than needing to be regenerated."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    period_type: Mapped[ReportPeriod] = mapped_column(
        Enum(ReportPeriod, name="report_period")
    )
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    file_path: Mapped[str] = mapped_column(String(300))
    # Null for one the scheduler generated automatically — nobody "did" that.
    generated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("household_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Null means not yet paid out — the only state this tracks; there's no
    # workflow beyond a manual admin toggle once they've actually sent the
    # money (see PROJECT_SPEC.md: reports are reference-only, this is too).
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    generated_by: Mapped[HouseholdUser | None] = relationship()


class PushSubscription(Base):
    """A browser's Web Push subscription for one household user. A user can
    have more than one (multiple devices/browsers), so this isn't keyed
    1:1 on household_user_id — `endpoint` is the natural unique key the
    Push API itself gives us."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    household_user_id: Mapped[int] = mapped_column(
        ForeignKey("household_users.id", ondelete="CASCADE")
    )
    endpoint: Mapped[str] = mapped_column(String(500), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    household_user: Mapped[HouseholdUser] = relationship()
