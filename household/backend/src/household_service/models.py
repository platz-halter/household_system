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
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
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
    # Outgoing chain links only (this task as the parent) — a task's own
    # "when I'm completed, also spawn..." list, shown/edited from this
    # task's own edit screen. Whether THIS task is itself someone else's
    # chain child is derived by querying task_chain_links for a row with
    # child_task_id == this task's id (see crud.list_tasks) rather than
    # a relationship here or a flag on this model — a flag could drift
    # from the link table actually saying; a query can't.
    chain_links: Mapped[list["TaskChainLink"]] = relationship(
        foreign_keys="TaskChainLink.parent_task_id",
        back_populates="parent_task",
        cascade="all, delete-orphan",
        order_by="TaskChainLink.position",
    )


class TaskChainLink(Base):
    """Defines one "chain task": when `parent_task_id` is completed, a
    one-off `TodoItem` instance of `child_task_id` is spawned for that
    specific occurrence (see crud._spawn_chain_children) — deliberately
    NOT an independent schedule of its own. A task that only ever
    exists as somebody's chain child has no recurrence of its own that
    matters and is excluded from the normal sweep/Home task list/direct
    completion entirely (see crud.list_tasks' `is_chain_child` and
    complete_task's own guard) — one source of instances per task, so
    the same real-world occurrence can't earn points twice and the
    scheduler can't manufacture duplicates of something only meant to
    exist as a reaction to its parent.

    `same_user=True` assigns the spawned todo directly to whoever
    completed the parent, bypassing the balancing tool entirely.
    `same_user=False` assigns it through the same fairness logic the
    balancer's sweep uses, run once immediately at spawn time (not left
    for the next daily sweep — a once-a-day cadence would leave a
    same-day chain todo sitting unassigned for hours), explicitly
    excluding whoever completed the parent (see TodoItem.exclude_user_id).

    Chains can run more than one level deep (a child can itself be a
    parent of further links) — `crud.create_chain_link` rejects a link
    that would create a cycle back to an ancestor, since an endless
    chore loop isn't something this is meant to allow."""

    __tablename__ = "task_chain_links"
    __table_args__ = (
        UniqueConstraint(
            "parent_task_id", "child_task_id", name="uq_chain_link_parent_child"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE")
    )
    child_task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE")
    )
    same_user: Mapped[bool] = mapped_column(Boolean, default=False)
    # Display/evaluation order among a task's own chain links — purely
    # cosmetic (which order they're listed/spawned in), not a dependency
    # order between different parents' chains.
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parent_task: Mapped[Task] = relationship(
        foreign_keys=[parent_task_id], back_populates="chain_links"
    )
    child_task: Mapped[Task] = relationship(foreign_keys=[child_task_id])


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
    recurring `Task` schedule — also how a chain task's spawned instance
    is represented (see TaskChainLink), rather than inventing a second
    kind of one-off item; reuses assigned_to/due_date/points/completion
    and everything the board/Home/push already do with a TodoItem."""

    __tablename__ = "todo_items"
    __table_args__ = (
        # Makes spawning idempotent: the same completion (spawned_by_
        # entry_id) can never spawn the same chain link's child twice,
        # even if something retries. Both columns are null for an
        # ordinary user-posted todo — Postgres treats NULL as distinct
        # from NULL in a unique constraint, so this never blocks two
        # ordinary todos from coexisting.
        UniqueConstraint(
            "chain_link_id", "spawned_by_entry_id", name="uq_todo_chain_spawn"
        ),
    )

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

    # Null for an ordinary user-posted todo. chain_link_id is which link
    # spawned this instance (ON DELETE SET NULL — if the link's later
    # removed, the already-spawned todo stays, it just loses the "why"
    # pointer). spawned_by_entry_id is the specific PointsEntry whose
    # completion triggered the spawn — works whether the parent was a
    # Task completion or another chain todo's completion (chains can run
    # more than one level deep) — paired with chain_link_id in the
    # unique constraint above for idempotent spawning.
    chain_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_chain_links.id", ondelete="SET NULL"), nullable=True
    )
    spawned_by_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("points_entries.id", ondelete="SET NULL"), nullable=True
    )
    # Only set for a "different person" chain spawn — whoever completed
    # the parent, who must NOT receive this todo. Enforced both at spawn
    # time (crud._spawn_chain_children) and by the daily sweep
    # (balancing.CandidateTodo.excluded_user_id), so a sweep run on a day
    # this is still unclaimed can't hand it straight back to them.
    exclude_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("household_users.id", ondelete="SET NULL"), nullable=True
    )

    created_by: Mapped[HouseholdUser] = relationship(foreign_keys=[created_by_id])
    assigned_to: Mapped[HouseholdUser | None] = relationship(
        foreign_keys=[assigned_to_id]
    )
    completed_by: Mapped[HouseholdUser | None] = relationship(
        foreign_keys=[completed_by_id]
    )
    chain_link: Mapped[TaskChainLink | None] = relationship(
        foreign_keys=[chain_link_id]
    )


class TakeoverStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    cancelled = "cancelled"


class TakeoverRequest(Base):
    """ "Can you take this over?" — whoever currently holds a board todo or
    a recurring task assignment can ask a specific other person to take
    it off their hands, for whatever reason ("don't have time right
    now"). Deliberately consent-based, not an instant handoff: the
    target has to accept before anything actually moves (see
    crud.accept_takeover_request) — asking isn't the same as reassigning
    (that's the admin-only crud.reassign_todo instead).

    Exactly one of `todo_item_id`/`task_assignment_id` is set (the
    CheckConstraint below) — a takeover request is for one specific
    held item, whichever kind it is. Only one PENDING request can exist
    per item at a time (the two partial unique indexes below) — asking
    two people at once would let both accept and race each other.

    `accept_takeover_request` re-validates the requester still holds
    the item with the same kind of conditional UPDATE `claim_todo` uses
    — the holder can change out from under a pending request (an admin
    reassign, the balancer, the requester going on break) between the
    ask and the answer."""

    __tablename__ = "takeover_requests"
    __table_args__ = (
        CheckConstraint(
            "(todo_item_id IS NOT NULL) != (task_assignment_id IS NOT NULL)",
            name="ck_takeover_exactly_one_item",
        ),
        Index(
            "uq_takeover_pending_todo",
            "todo_item_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "uq_takeover_pending_assignment",
            "task_assignment_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("household_users.id", ondelete="CASCADE")
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("household_users.id", ondelete="CASCADE")
    )
    todo_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("todo_items.id", ondelete="CASCADE"), nullable=True
    )
    task_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_assignments.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[TakeoverStatus] = mapped_column(
        Enum(TakeoverStatus, name="takeover_status"), default=TakeoverStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requester: Mapped[HouseholdUser] = relationship(foreign_keys=[requester_id])
    target: Mapped[HouseholdUser] = relationship(foreign_keys=[target_id])
    todo_item: Mapped[TodoItem | None] = relationship(foreign_keys=[todo_item_id])
    task_assignment: Mapped[TaskAssignment | None] = relationship(
        foreign_keys=[task_assignment_id]
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
    # foreign_keys explicit: TodoItem now has a SECOND FK into
    # points_entries (spawned_by_entry_id, for chain-spawned todos),
    # which otherwise makes this join ambiguous — two separate FK
    # constraints directly between the same pair of tables.
    todo_item: Mapped[TodoItem | None] = relationship(foreign_keys=[todo_item_id])


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
