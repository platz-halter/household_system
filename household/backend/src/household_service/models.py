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
    ForeignKey,
    Integer,
    String,
    Table,
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

    # Weekly schedule, purely descriptive for now: which weekdays this task
    # recurs on (0=Monday..6=Sunday) and how many times per day. There's no
    # auto-assignment yet (balancing tool is a later phase) — this just lets
    # the frontend show "today's chores".
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


class HouseholdSettings(Base):
    """Singleton config row — id is always 1."""

    __tablename__ = "household_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    weekly_points_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
