import calendar
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from household_service import balancing, push
from household_service import reports as reports_pdf
from household_service.models import (
    Category,
    HouseholdSettings,
    HouseholdUser,
    PointsEntry,
    PointsSource,
    PushSubscription,
    Recurrence,
    Report,
    ReportPeriod,
    Task,
    TaskAssignment,
    TodoItem,
    TodoStatus,
)
from household_service.schemas import (
    CategoryIn,
    CategoryUpdate,
    HouseholdSettingsUpdate,
    HouseholdUserUpdate,
    PushSubscriptionIn,
    ReportCreate,
    TaskCreate,
    TaskUpdate,
    TodoCreate,
    TodoUpdate,
)

# ---- Household users -------------------------------------------------


async def get_or_create_household_user(db: AsyncSession, subject: str) -> HouseholdUser:
    result = await db.execute(
        select(HouseholdUser).where(HouseholdUser.subject == subject)
    )
    user = result.scalar_one_or_none()
    if user:
        return user
    user = HouseholdUser(subject=subject, display_name=subject)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_household_user(db: AsyncSession, user_id: int) -> HouseholdUser | None:
    return await db.get(HouseholdUser, user_id)


async def list_household_users(db: AsyncSession) -> list[HouseholdUser]:
    result = await db.execute(
        select(HouseholdUser).order_by(HouseholdUser.display_name)
    )
    return list(result.scalars().all())


async def update_household_user(
    db: AsyncSession, user: HouseholdUser, data: HouseholdUserUpdate
) -> HouseholdUser:
    going_on_break = data.on_break is True and not user.on_break
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.on_break is not None:
        user.on_break = data.on_break
    if going_on_break:
        await _release_user_assignments(db, user)
    await db.commit()
    await db.refresh(user)
    return user


async def _release_user_assignments(db: AsyncSession, user: HouseholdUser) -> None:
    """Frees up whatever this user hasn't finished yet, so the next
    balancer run (or another person claiming a board item) can pick it
    back up instead of it staying stuck with someone on break. Only
    touches assignments with real work still outstanding — see
    _remaining_points (partial progress reduces, but doesn't necessarily
    zero out, what's left)."""
    today = datetime.now(UTC).date()
    result = await db.execute(
        select(TaskAssignment)
        .options(selectinload(TaskAssignment.task))
        .where(
            TaskAssignment.household_user_id == user.id,
            TaskAssignment.period_end >= today,
        )
    )
    for a in result.scalars().all():
        if await _remaining_points(db, a.task, a.period_start, a.period_end) > 0:
            await db.delete(a)

    todos_result = await db.execute(
        select(TodoItem).where(
            TodoItem.assigned_to_id == user.id, TodoItem.status == TodoStatus.open
        )
    )
    for todo in todos_result.scalars().all():
        todo.assigned_to_id = None


async def set_user_image(
    db: AsyncSession, user: HouseholdUser, filename: str
) -> HouseholdUser:
    user.image_path = filename
    await db.commit()
    await db.refresh(user)
    return user


async def clear_user_image(db: AsyncSession, user: HouseholdUser) -> HouseholdUser:
    user.image_path = None
    await db.commit()
    await db.refresh(user)
    return user


# ---- Categories -------------------------------------------------------


async def list_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: int) -> Category | None:
    return await db.get(Category, category_id)


async def create_category(db: AsyncSession, data: CategoryIn) -> Category:
    category = Category(name=data.name, icon=data.icon)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, category: Category, data: CategoryUpdate
) -> Category:
    if data.name is not None:
        category.name = data.name
    if data.icon is not None:
        category.icon = data.icon
    await db.commit()
    await db.refresh(category)
    return category


async def delete_category(db: AsyncSession, category: Category) -> None:
    await db.delete(category)
    await db.commit()


# ---- Tasks --------------------------------------------------------------


def _task_query():
    return select(Task).options(selectinload(Task.categories))


async def get_task(db: AsyncSession, task_id: int) -> Task | None:
    result = await db.execute(_task_query().where(Task.id == task_id))
    return result.scalar_one_or_none()


async def list_tasks(
    db: AsyncSession, *, active: bool | None = None, category_id: int | None = None
) -> list[Task]:
    stmt = _task_query()
    if active is not None:
        stmt = stmt.where(Task.active == active)
    if category_id is not None:
        stmt = stmt.join(Task.categories).where(Category.id == category_id)
    result = await db.execute(stmt.order_by(Task.name))
    return list(result.scalars().unique().all())


async def _resolve_categories(
    db: AsyncSession, category_ids: list[int]
) -> list[Category]:
    if not category_ids:
        return []
    result = await db.execute(select(Category).where(Category.id.in_(category_ids)))
    found = list(result.scalars().all())
    missing = set(category_ids) - {c.id for c in found}
    if missing:
        raise ValueError(f"Unknown category id(s): {sorted(missing)}")
    return found


async def create_task(db: AsyncSession, data: TaskCreate) -> Task:
    categories = await _resolve_categories(db, data.category_ids)
    task = Task(
        name=data.name,
        description=data.description,
        points=data.points,
        active=data.active,
        recurrence=data.recurrence,
        weekdays=data.weekdays,
        times_per_day=data.times_per_day,
        ramp_up_enabled=data.ramp_up_enabled,
        ramp_up_bonus_points=data.ramp_up_bonus_points,
        categories=categories,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task, attribute_names=["categories", "created_at", "updated_at"])
    return task


async def update_task(db: AsyncSession, task: Task, data: TaskUpdate) -> Task:
    if data.name is not None:
        task.name = data.name
    if data.description is not None:
        task.description = data.description
    if data.points is not None:
        task.points = data.points
    if data.active is not None:
        task.active = data.active
    if data.recurrence is not None:
        task.recurrence = data.recurrence
    if data.weekdays is not None:
        task.weekdays = data.weekdays
    if task.recurrence == Recurrence.weekly and not task.weekdays:
        raise ValueError("a weekly task needs at least one weekday")
    if task.recurrence != Recurrence.weekly:
        task.weekdays = None
    if data.times_per_day is not None:
        task.times_per_day = data.times_per_day
    if data.ramp_up_enabled is not None:
        task.ramp_up_enabled = data.ramp_up_enabled
    if data.ramp_up_bonus_points is not None:
        task.ramp_up_bonus_points = data.ramp_up_bonus_points
    if data.category_ids is not None:
        task.categories = await _resolve_categories(db, data.category_ids)
    await db.commit()
    await db.refresh(task, attribute_names=["categories", "updated_at"])
    return task


async def delete_task(db: AsyncSession, task: Task) -> None:
    await db.delete(task)
    await db.commit()


async def _completions_today_count(db: AsyncSession, task_id: int) -> int:
    today = datetime.now(UTC).date()
    since = datetime.combine(today, time.min, tzinfo=UTC)
    until = datetime.combine(today, time.max, tzinfo=UTC)
    count = await db.scalar(
        select(func.count(PointsEntry.id)).where(
            PointsEntry.task_id == task_id,
            PointsEntry.earned_at >= since,
            PointsEntry.earned_at <= until,
        )
    )
    return int(count or 0)


async def task_completions_today(db: AsyncSession) -> dict[int, int]:
    """How many times each task has already been completed today, by
    anyone — feeds the Home page's "Today" list (a task scheduled
    `times_per_day` times a day disappears once that's been hit) and the
    same cap complete_task enforces below, so the UI and the backend
    agree on when a task is "done for today"."""
    today = datetime.now(UTC).date()
    since = datetime.combine(today, time.min, tzinfo=UTC)
    until = datetime.combine(today, time.max, tzinfo=UTC)
    result = await db.execute(
        select(PointsEntry.task_id, func.count(PointsEntry.id))
        .where(
            PointsEntry.task_id.isnot(None),
            PointsEntry.earned_at >= since,
            PointsEntry.earned_at <= until,
        )
        .group_by(PointsEntry.task_id)
    )
    return {task_id: count for task_id, count in result.all()}


async def complete_task(
    db: AsyncSession, task: Task, user: HouseholdUser
) -> PointsEntry:
    """Logs one completion of `task` by `user` and awards points, including
    the configured ramp-up bonus if this user is (so far) the only one who
    has ever completed this task. Rejects a completion past the task's own
    `times_per_day` for today (by anyone, not just this user) — without
    this, a 1x/day task never actually went away, and repeated taps just
    kept awarding points indefinitely."""
    done_today = await _completions_today_count(db, task.id)
    if done_today >= task.times_per_day:
        raise ValueError(
            f'"{task.name}" has already been completed {task.times_per_day}x today'
        )

    bonus = 0
    if task.ramp_up_enabled:
        result = await db.execute(
            select(func.count(func.distinct(PointsEntry.household_user_id))).where(
                PointsEntry.task_id == task.id, PointsEntry.household_user_id != user.id
            )
        )
        other_completers = result.scalar_one()
        if other_completers == 0:
            bonus = task.ramp_up_bonus_points

    entry = PointsEntry(
        household_user_id=user.id,
        points=task.points + bonus,
        source=PointsSource.task,
        task_id=task.id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(
        entry, attribute_names=["household_user", "task", "todo_item", "earned_at"]
    )
    return entry


# ---- Todo board -------------------------------------------------------


def _todo_due_date(due_in_days: int | None) -> date | None:
    if due_in_days is None:
        return None
    return datetime.now(UTC).date() + timedelta(days=due_in_days)


def _todo_query():
    return select(TodoItem).options(
        selectinload(TodoItem.created_by),
        selectinload(TodoItem.assigned_to),
        selectinload(TodoItem.completed_by),
    )


async def get_todo(db: AsyncSession, todo_id: int) -> TodoItem | None:
    result = await db.execute(_todo_query().where(TodoItem.id == todo_id))
    return result.scalar_one_or_none()


async def list_todos(
    db: AsyncSession,
    *,
    status: TodoStatus | None = None,
    assigned_to_id: int | None = None,
) -> list[TodoItem]:
    stmt = _todo_query()
    if status is not None:
        stmt = stmt.where(TodoItem.status == status)
    if assigned_to_id is not None:
        stmt = stmt.where(TodoItem.assigned_to_id == assigned_to_id)
    result = await db.execute(
        stmt.order_by(TodoItem.due_date.asc().nullslast(), TodoItem.created_at.desc())
    )
    return list(result.scalars().all())


async def create_todo(
    db: AsyncSession, data: TodoCreate, creator: HouseholdUser
) -> TodoItem:
    if (
        data.assigned_to_id is not None
        and await get_household_user(db, data.assigned_to_id) is None
    ):
        raise ValueError(f"Unknown household user id: {data.assigned_to_id}")
    todo = TodoItem(
        title=data.title,
        description=data.description,
        points=data.points,
        due_date=_todo_due_date(data.due_in_days),
        assigned_to_id=data.assigned_to_id,
        created_by_id=creator.id,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(
        todo,
        attribute_names=["created_by", "assigned_to", "completed_by", "created_at"],
    )
    return todo


async def update_todo(db: AsyncSession, todo: TodoItem, data: TodoUpdate) -> TodoItem:
    if data.title is not None:
        todo.title = data.title
    if data.description is not None:
        todo.description = data.description
    if data.points is not None:
        todo.points = data.points
    if data.due_in_days is not None:
        todo.due_date = _todo_due_date(data.due_in_days)
    if data.assigned_to_id is not None:
        if await get_household_user(db, data.assigned_to_id) is None:
            raise ValueError(f"Unknown household user id: {data.assigned_to_id}")
        todo.assigned_to_id = data.assigned_to_id
    await db.commit()
    await db.refresh(
        todo, attribute_names=["created_by", "assigned_to", "completed_by"]
    )
    return todo


async def complete_todo(
    db: AsyncSession, todo: TodoItem, user: HouseholdUser
) -> TodoItem:
    todo.status = TodoStatus.completed
    todo.completed_by_id = user.id
    todo.completed_at = datetime.now(UTC)
    entry = PointsEntry(
        household_user_id=user.id,
        points=todo.points,
        source=PointsSource.todo,
        todo_item_id=todo.id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(todo, attribute_names=["completed_by", "completed_at", "status"])
    return todo


async def cancel_todo(db: AsyncSession, todo: TodoItem) -> TodoItem:
    todo.status = TodoStatus.cancelled
    await db.commit()
    await db.refresh(todo, attribute_names=["status"])
    return todo


async def delete_todo(db: AsyncSession, todo: TodoItem) -> None:
    await db.delete(todo)
    await db.commit()


async def claim_todo(
    db: AsyncSession, todo_id: int, user: HouseholdUser
) -> TodoItem | None:
    """Self-assigns an open, unclaimed board item. A conditional UPDATE
    (not a read-then-write) so two people tapping "claim" on the same
    item at the same moment can't both win it — whichever request's
    UPDATE actually matches a row (rowcount 1) gets it; the other sees
    rowcount 0 and the caller turns that into a 409."""
    result = await db.execute(
        update(TodoItem)
        .where(
            TodoItem.id == todo_id,
            TodoItem.status == TodoStatus.open,
            TodoItem.assigned_to_id.is_(None),
        )
        .values(assigned_to_id=user.id)
    )
    await db.commit()
    if result.rowcount == 0:
        return None
    return await get_todo(db, todo_id)


# ---- Task assignments / balancing tool ----------------------------------


# Minimum age before an unclaimed board todo is swept up automatically —
# gives a person first crack at claiming it themselves before the daily
# balancing run does it for them.
CLAIM_WINDOW = timedelta(hours=6)


@dataclass
class _UserTally:
    user: HouseholdUser
    new_task_count: int = 0
    new_todo_count: int = 0
    new_expected_points: int = 0
    # The mid-week pull pass, tracked separately from the above since
    # it's a reshuffle of existing work, not new work.
    reassigned_in_count: int = 0
    reassigned_out_count: int = 0
    reassigned_net_points: int = 0


@dataclass
class BalancingRunOutcome:
    week_start: date
    week_end: date
    month_start: date
    month_end: date
    new_task_assignments: list[TaskAssignment] = field(default_factory=list)
    new_todo_assignments: list[TodoItem] = field(default_factory=list)
    # (assignment, from_user_id, to_user_id, points transferred)
    reassignments: list[tuple[TaskAssignment, int, int, int]] = field(
        default_factory=list
    )
    unassigned_task_count: int = 0
    unassigned_todo_count: int = 0
    user_summaries: list[_UserTally] = field(default_factory=list)


def _expected_instances(task: Task) -> int:
    if task.recurrence == Recurrence.weekly:
        return len(task.weekdays or []) * task.times_per_day
    if task.recurrence == Recurrence.monthly:
        return task.times_per_day
    return 0  # daily tasks are never balancer candidates


def _expected_points(task: Task) -> int:
    """How many points this task is worth over its whole period — a
    weekly task scheduled 3x/week at 2x/day earns more than one run
    through the Home "complete" button, so the balancer should weigh it
    accordingly rather than treating every task as a single point value.
    Used for a BRAND NEW assignment, where nothing's been done yet (see
    _remaining_points for an existing one, which may be partway done)."""
    return _expected_instances(task) * task.points


def _task_period(
    task: Task, week_start: date, week_end: date, month_start: date, month_end: date
) -> tuple[date, date]:
    if task.recurrence == Recurrence.weekly:
        return week_start, week_end
    return month_start, month_end  # Recurrence.monthly — the only other candidate kind


async def _completed_instance_count(
    db: AsyncSession, task_id: int, period_start: date, period_end: date
) -> int:
    since = datetime.combine(period_start, time.min, tzinfo=UTC)
    until = datetime.combine(period_end, time.max, tzinfo=UTC)
    count = await db.scalar(
        select(func.count(PointsEntry.id)).where(
            PointsEntry.task_id == task_id,
            PointsEntry.earned_at >= since,
            PointsEntry.earned_at <= until,
        )
    )
    return int(count or 0)


async def _remaining_points(
    db: AsyncSession, task: Task, period_start: date, period_end: date
) -> int:
    """What's left of this task's whole-period value — how many of its
    expected instances across the whole week/month (not just "today")
    nobody's logged yet, times its points. Counts a completion by ANYONE,
    not just the assigned holder: someone else pitching in still reduces
    what's genuinely outstanding. There's no separate "done" flag on
    TaskAssignment — this check IS the status, kept in sync with
    whatever PointsEntry rows actually exist rather than a second piece
    of state that could drift from them."""
    expected = _expected_instances(task)
    if expected <= 0:
        return 0
    done = await _completed_instance_count(db, task.id, period_start, period_end)
    return max(0, expected - done) * task.points


async def list_current_assignments(
    db: AsyncSession, *, as_of: date | None = None
) -> list[TaskAssignment]:
    as_of = as_of or datetime.now(UTC).date()
    result = await db.execute(
        select(TaskAssignment)
        .options(
            selectinload(TaskAssignment.task),
            selectinload(TaskAssignment.household_user),
        )
        .where(TaskAssignment.period_start <= as_of, TaskAssignment.period_end >= as_of)
        .order_by(TaskAssignment.period_start)
    )
    return list(result.scalars().all())


async def run_balancing(
    db: AsyncSession, *, as_of: date | None = None
) -> BalancingRunOutcome:
    """The auto-balancing tool (PROJECT_SPEC.md), in two passes:

    1. Sweep — hand out anything not yet assigned this period: every
       active weekly/monthly task without an assignment yet, and every
       open board todo nobody's claimed (sitting unclaimed longer than
       CLAIM_WINDOW, so a person gets first crack at it).
    2. Rebalance — recompute everyone's load after the sweep, then pull
       an unfinished, non-ramp-up task from whoever's most ahead to
       whoever's still meaningfully behind (balancing.rebalance). Running
       the sweep first means a freshly-freed item gets a chance to
       absorb the imbalance on its own before anything existing assigned
       work is disrupted.

    Always stamps `last_balance_run` to today — mirrors
    send_weekly_nudge's own stamping, so a manual Admin-panel run and the
    automatic daily schedule (scheduler.py) can't double-run the same
    day. Unlike the old weekly/monthly-only cadence, this now runs daily
    on purpose: pass 2 needs to re-check for imbalances more often than
    once a period to actually catch someone falling behind mid-week, not
    just at its start."""
    as_of = as_of or datetime.now(UTC).date()
    settings = await get_settings_row(db)
    week_start, week_end = _resolve_period(
        ReportPeriod.week, as_of, settings.week_start_weekday
    )
    month_start, month_end = _resolve_period(ReportPeriod.month, as_of)

    all_users = await list_household_users(db)
    eligible = [u for u in all_users if not u.on_break]
    eligible_by_id = {u.id: u for u in eligible}

    settings.last_balance_run = as_of

    # No early-return for "nobody eligible" — fall through to the normal
    # path so candidates still get counted (balancing.balance() returns
    # everything as unassigned when `users` is empty), which is what
    # makes unassigned_task_count/unassigned_todo_count mean something
    # real in that case instead of silently reading 0/0.

    # ---- seed everyone's starting load for this run --------------------
    # Matched by OVERLAP with today (not an exact period_start match) —
    # an exact match would double-assign the same task if the admin ever
    # changes week_start_weekday mid-period, since that shifts what
    # "this week's start date" even resolves to for a task whose
    # existing assignment was computed under the old boundary.
    current_assignments_result = await db.execute(
        select(TaskAssignment)
        .options(selectinload(TaskAssignment.task))
        .where(TaskAssignment.period_start <= as_of, TaskAssignment.period_end >= as_of)
    )
    current_assignments = list(current_assignments_result.scalars().all())
    assignment_by_id = {a.id: a for a in current_assignments}
    remaining_by_assignment = {
        a.id: await _remaining_points(db, a.task, a.period_start, a.period_end)
        for a in current_assignments
    }

    load_points: dict[int, int] = dict.fromkeys(eligible_by_id, 0)
    load_count: dict[int, int] = dict.fromkeys(eligible_by_id, 0)
    for a in current_assignments:
        if a.household_user_id not in load_points:
            continue  # now on break (or otherwise ineligible) — doesn't count against the cap
        remaining = remaining_by_assignment[a.id]
        if remaining <= 0:
            continue
        load_points[a.household_user_id] += remaining
        load_count[a.household_user_id] += 1

    open_todos_result = await db.execute(
        select(TodoItem).where(
            TodoItem.status == TodoStatus.open, TodoItem.assigned_to_id.isnot(None)
        )
    )
    for todo in open_todos_result.scalars().all():
        if todo.assigned_to_id not in load_points:
            continue
        load_points[todo.assigned_to_id] += todo.points
        load_count[todo.assigned_to_id] += 1

    week_since = datetime.combine(week_start, time.min, tzinfo=UTC)
    points_this_week = {
        u.id: await points_for_user_since(db, u.id, week_since) for u in eligible
    }

    def _balancing_users() -> list[balancing.EligibleUser]:
        # Re-read load_points/load_count each call — both passes below
        # share and mutate this same running state.
        return [
            balancing.EligibleUser(
                user_id=u.id,
                points_this_week=points_this_week[u.id],
                already_assigned_points=load_points[u.id],
                already_assigned_count=load_count[u.id],
            )
            for u in eligible
        ]

    # ---- pass 1: sweep anything not yet assigned this period -----------
    candidate_tasks: list[balancing.CandidateTask] = []
    task_period_map: dict[int, tuple[date, date]] = {}
    task_by_id: dict[int, Task] = {}
    tasks_result = await db.execute(
        select(Task).where(Task.active.is_(True), Task.recurrence != Recurrence.daily)
    )
    already_assigned_task_ids = {a.task_id for a in current_assignments}
    for task in tasks_result.scalars().all():
        task_by_id[task.id] = task
        p_start, p_end = _task_period(
            task, week_start, week_end, month_start, month_end
        )
        if task.id in already_assigned_task_ids:
            continue
        expected = _expected_points(task)
        if expected <= 0:
            continue
        history_result = await db.execute(
            select(TaskAssignment.household_user_id)
            .where(
                TaskAssignment.task_id == task.id, TaskAssignment.period_start < p_start
            )
            .order_by(TaskAssignment.period_start.desc())
            .limit(2)
        )
        history = [row[0] for row in history_result.all()]
        candidate_tasks.append(
            balancing.CandidateTask(
                task_id=task.id,
                expected_points=expected,
                ramp_up_enabled=task.ramp_up_enabled,
                last_assignee_id=history[0] if history else None,
                recent_assignee_ids=frozenset(history),
            )
        )
        task_period_map[task.id] = (p_start, p_end)

    claimable_cutoff = datetime.now(UTC) - CLAIM_WINDOW
    unclaimed_result = await db.execute(
        _todo_query().where(
            TodoItem.status == TodoStatus.open,
            TodoItem.assigned_to_id.is_(None),
            TodoItem.created_at <= claimable_cutoff,
        )
    )
    unclaimed_todos = {t.id: t for t in unclaimed_result.scalars().all()}
    candidate_todos = [
        balancing.CandidateTodo(todo_id=t.id, points=t.points)
        for t in unclaimed_todos.values()
    ]

    total_candidates = len(candidate_tasks) + len(candidate_todos)
    # Count-based cap (not points-based) so one person can't be handed a
    # long string of small items either — shared by both passes, so a
    # recipient who already hit it via the sweep can't also be a pull
    # target in the same run, and vice versa.
    max_new_items_per_user = (
        math.ceil(total_candidates / len(eligible)) + 1 if eligible else 0
    )

    sweep_result = balancing.balance(
        users=_balancing_users(),
        tasks=candidate_tasks,
        todos=candidate_todos,
        max_new_items_per_user=max_new_items_per_user,
    )

    new_task_assignments: list[TaskAssignment] = []
    for task_id, user_id in sweep_result.task_assignments.items():
        p_start, p_end = task_period_map[task_id]
        row = TaskAssignment(
            task_id=task_id,
            household_user_id=user_id,
            period_start=p_start,
            period_end=p_end,
        )
        db.add(row)
        new_task_assignments.append(row)
        load_points[user_id] += _expected_points(task_by_id[task_id])
        load_count[user_id] += 1

    new_todo_assignments: list[TodoItem] = []
    for todo_id, user_id in sweep_result.todo_assignments.items():
        todo = unclaimed_todos[todo_id]
        todo.assigned_to_id = user_id
        new_todo_assignments.append(todo)
        load_points[user_id] += todo.points
        load_count[user_id] += 1

    # ---- pass 2: pull unfinished work from whoever's now most ahead ----
    pullable: list[balancing.PullableAssignment] = []
    for a in current_assignments:
        remaining = remaining_by_assignment[a.id]
        if remaining <= 0 or a.household_user_id not in eligible_by_id:
            continue
        done_count = await _completed_instance_count(
            db, a.task_id, a.period_start, a.period_end
        )
        pullable.append(
            balancing.PullableAssignment(
                assignment_id=a.id,
                holder_id=a.household_user_id,
                remaining_points=remaining,
                ramp_up_enabled=a.task.ramp_up_enabled,
                has_progress=done_count > 0,
                already_reassigned=a.reassigned_at is not None,
                assigned_today=a.created_at.astimezone(UTC).date() >= as_of,
            )
        )

    moves = balancing.rebalance(
        users=_balancing_users(),
        assignments=pullable,
        weekly_points_goal=settings.weekly_points_goal,
        max_new_items_per_user=max_new_items_per_user,
    )

    reassignments: list[tuple[TaskAssignment, int, int, int]] = []
    now = datetime.now(UTC)
    for assignment_id, from_uid, to_uid in moves:
        row = assignment_by_id[assignment_id]
        pts = remaining_by_assignment[assignment_id]
        row.household_user_id = to_uid
        row.reassigned_at = now
        reassignments.append((row, from_uid, to_uid, pts))
        load_points[from_uid] -= pts
        load_points[to_uid] += pts
        load_count[to_uid] += 1

    await db.commit()
    for row in new_task_assignments:
        await db.refresh(row, attribute_names=["task", "household_user"])
    for todo in new_todo_assignments:
        await db.refresh(todo, attribute_names=["assigned_to"])
    for row, _from_uid, _to_uid, _pts in reassignments:
        await db.refresh(row, attribute_names=["task", "household_user"])

    # ---- tallies + one push per affected user ---------------------------
    tallies: dict[int, _UserTally] = {u.id: _UserTally(user=u) for u in eligible}
    for row in new_task_assignments:
        t = tallies[row.household_user_id]
        t.new_task_count += 1
        t.new_expected_points += _expected_points(row.task)
    for todo in new_todo_assignments:
        t = tallies[todo.assigned_to_id]
        t.new_todo_count += 1
        t.new_expected_points += todo.points
    for row, from_uid, to_uid, pts in reassignments:
        if from_uid in tallies:
            tallies[from_uid].reassigned_out_count += 1
            tallies[from_uid].reassigned_net_points -= pts
        tallies[to_uid].reassigned_in_count += 1
        tallies[to_uid].reassigned_net_points += pts

    user_summaries = [
        t
        for t in tallies.values()
        if t.new_task_count
        or t.new_todo_count
        or t.reassigned_in_count
        or t.reassigned_out_count
    ]

    for t in user_summaries:
        subs = await get_subscriptions_for_user(db, t.user.id)
        if not subs:
            continue
        parts = []
        total_new = t.new_task_count + t.new_todo_count
        if total_new:
            parts.append(
                f"{total_new} new item{'s' if total_new != 1 else ''} "
                f"(+{t.new_expected_points} pts)"
            )
        if t.reassigned_in_count:
            parts.append(
                f"{t.reassigned_in_count} task{'s' if t.reassigned_in_count != 1 else ''} "
                "moved to you to even out the week"
            )
        if t.reassigned_out_count:
            parts.append(
                f"{t.reassigned_out_count} task{'s' if t.reassigned_out_count != 1 else ''} "
                "moved to someone else to even out the week"
            )
        await push.send_to_subscriptions(
            db,
            subs,
            {
                "title": "Household balancing update",
                "body": "; ".join(parts) + ".",
                "url": "/home",
            },
        )

    return BalancingRunOutcome(
        week_start=week_start,
        week_end=week_end,
        month_start=month_start,
        month_end=month_end,
        new_task_assignments=new_task_assignments,
        new_todo_assignments=new_todo_assignments,
        reassignments=reassignments,
        unassigned_task_count=len(sweep_result.unassigned_task_ids),
        unassigned_todo_count=len(sweep_result.unassigned_todo_ids),
        user_summaries=user_summaries,
    )


async def run_scheduled_balancing_if_due(
    db: AsyncSession,
) -> BalancingRunOutcome | None:
    """Called hourly by household_service.scheduler, same pattern as
    run_scheduled_nudge_if_due — but a daily job now (not just Monday/the
    1st), since the mid-week rebalance pass needs to re-check for
    imbalances more often than once a period to actually catch someone
    falling behind during the week. run_balancing itself stamps
    last_balance_run, so once today's run has happened (by whichever
    trigger got there first) every later tick this same day is a no-op."""
    settings = await get_settings_row(db)
    today = datetime.now(UTC).date()
    if settings.last_balance_run == today:
        return None
    return await run_balancing(db, as_of=today)


# ---- Points -------------------------------------------------------------


def _points_entry_query():
    return select(PointsEntry).options(
        selectinload(PointsEntry.household_user),
        selectinload(PointsEntry.task),
        selectinload(PointsEntry.todo_item),
    )


async def recent_points(db: AsyncSession, limit: int = 20) -> list[PointsEntry]:
    result = await db.execute(
        _points_entry_query().order_by(PointsEntry.earned_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def daily_activity(
    db: AsyncSession,
    *,
    since: date,
    until: date,
    household_user_id: int | None = None,
) -> list[tuple[date, int]]:
    """Points earned per calendar day, summed across sources — feeds the
    GitHub-style activity heatmap. Days with no activity are simply absent
    from the result; the caller fills gaps with zero."""
    day = func.date(PointsEntry.earned_at)
    stmt = (
        select(day.label("day"), func.sum(PointsEntry.points).label("total"))
        .where(
            func.date(PointsEntry.earned_at) >= since,
            func.date(PointsEntry.earned_at) <= until,
        )
        .group_by(day)
        .order_by(day)
    )
    if household_user_id is not None:
        stmt = stmt.where(PointsEntry.household_user_id == household_user_id)
    result = await db.execute(stmt)
    return [(row.day, int(row.total)) for row in result.all()]


async def resolve_leaderboard_bounds(
    db: AsyncSession, period: str | None
) -> tuple[datetime | None, datetime | None]:
    """Translates a named period ("this_week"/"last_week"/"this_month"/
    "all"/None) into concrete since/until bounds, using the admin's
    configured week_start_weekday — resolved here, server-side, in UTC,
    so neither Home nor Stats needs to know that setting (or juggle the
    local-vs-UTC day-boundary gap the old client-side date math had) just
    to ask for "this week". `since`/`until` passed directly by the caller
    (the pre-existing mechanism) still work unchanged; `period` is just a
    more convenient way to ask for one of these four common cases."""
    if period is None or period == "all":
        return None, None
    settings = await get_settings_row(db)
    today = datetime.now(UTC).date()
    if period == "this_week":
        return _start_of_this_week(settings.week_start_weekday), None
    if period == "last_week":
        this_week_start, _ = week_bounds(today, settings.week_start_weekday)
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(days=1)
        return (
            datetime.combine(last_week_start, time.min, tzinfo=UTC),
            datetime.combine(last_week_end, time.max, tzinfo=UTC),
        )
    if period == "this_month":
        return datetime.combine(today.replace(day=1), time.min, tzinfo=UTC), None
    raise ValueError(f"Unknown period: {period}")


async def leaderboard(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    include_user_id: int | None = None,
) -> list[tuple[HouseholdUser, int]]:
    """Total points per non-break, non-viewer user, highest first. Users
    on break are excluded entirely (not just zeroed) per the break-mode
    spec — break only hides someone from everyone ELSE's leaderboard/
    assignments, it doesn't touch their actual points, which keep
    accumulating normally underneath (see complete_task/complete_todo —
    neither checks on_break at all). Viewers are excluded for a
    different reason: `can_write` already blocks them from completing
    anything, so they can only ever appear pinned at 0 — pure clutter,
    not a real ranking entry. Uses the cached `HouseholdUser.role` hint
    (synced in `_self` on nearly every request, see its own docstring),
    treating an unsynced NULL as "not known to be a viewer" rather than
    excluding it, so a role this cache hasn't caught up to yet can't
    accidentally hide a real admin/user. `include_user_id` punches one
    specific user back in regardless of break OR viewer status — for a
    user checking their OWN standing (e.g. Home's "points this week"
    card), which needs their real total, not a forced 0 just because
    the household-wide ranking view would otherwise exclude them. Users
    with no completions in range still appear, with a total of 0."""
    points_subq = select(PointsEntry.household_user_id, PointsEntry.points)
    if since is not None:
        points_subq = points_subq.where(PointsEntry.earned_at >= since)
    if until is not None:
        points_subq = points_subq.where(PointsEntry.earned_at <= until)
    points_subq = points_subq.subquery()

    total = func.coalesce(func.sum(points_subq.c.points), 0)
    stmt = (
        select(HouseholdUser, total.label("total"))
        .outerjoin(points_subq, points_subq.c.household_user_id == HouseholdUser.id)
        .where(
            or_(HouseholdUser.on_break.is_(False), HouseholdUser.id == include_user_id),
            or_(
                HouseholdUser.role.is_(None),
                HouseholdUser.role != "viewer",
                HouseholdUser.id == include_user_id,
            ),
        )
        .group_by(HouseholdUser.id)
        .order_by(total.desc())
    )
    result = await db.execute(stmt)
    return [(user, int(total_points)) for user, total_points in result.all()]


async def points_for_user_since(
    db: AsyncSession, household_user_id: int, since: datetime
) -> int:
    total = await db.scalar(
        select(func.coalesce(func.sum(PointsEntry.points), 0)).where(
            PointsEntry.household_user_id == household_user_id,
            PointsEntry.earned_at >= since,
        )
    )
    return int(total or 0)


async def leaderboard_for_period(
    db: AsyncSession, *, since: datetime, until: datetime
) -> list[tuple[HouseholdUser, int]]:
    """Like `leaderboard`, but for a historical report: includes users
    regardless of their CURRENT on_break status (break mode affects the
    live leaderboard only — it shouldn't rewrite what already happened),
    and only users who actually earned something in the period."""
    total = func.sum(PointsEntry.points)
    stmt = (
        select(HouseholdUser, total.label("total"))
        .join(PointsEntry, PointsEntry.household_user_id == HouseholdUser.id)
        .where(PointsEntry.earned_at >= since, PointsEntry.earned_at <= until)
        .group_by(HouseholdUser.id)
        .order_by(total.desc())
    )
    result = await db.execute(stmt)
    return [(user, int(total_points)) for user, total_points in result.all()]


# ---- Settings -----------------------------------------------------------


async def get_settings_row(db: AsyncSession) -> HouseholdSettings:
    settings = await db.get(HouseholdSettings, 1)
    if settings is None:
        settings = HouseholdSettings(id=1, weekly_points_goal=None)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def update_settings(
    db: AsyncSession, data: HouseholdSettingsUpdate
) -> HouseholdSettings:
    settings = await get_settings_row(db)
    settings.weekly_points_goal = data.weekly_points_goal
    settings.points_to_money_rate = data.points_to_money_rate
    settings.currency = data.currency
    settings.nudge_weekday = data.nudge_weekday
    settings.nudge_hour = data.nudge_hour
    settings.week_start_weekday = data.week_start_weekday
    settings.auto_report_enabled = data.auto_report_enabled
    await db.commit()
    await db.refresh(settings)
    return settings


# ---- Web Push -------------------------------------------------------------


async def upsert_push_subscription(
    db: AsyncSession, household_user_id: int, data: PushSubscriptionIn
) -> PushSubscription:
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(endpoint=data.endpoint)
        db.add(sub)
    sub.household_user_id = household_user_id
    sub.p256dh = data.keys.p256dh
    sub.auth = data.keys.auth
    await db.commit()
    await db.refresh(sub)
    return sub


async def remove_push_subscription(db: AsyncSession, endpoint: str) -> bool:
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return False
    await db.delete(sub)
    await db.commit()
    return True


async def get_subscriptions_for_user(
    db: AsyncSession, household_user_id: int
) -> list[PushSubscription]:
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.household_user_id == household_user_id
        )
    )
    return list(result.scalars().all())


async def notify_todo_assigned(
    db: AsyncSession, todo: TodoItem, requested_by: HouseholdUser
) -> None:
    """Fire-and-forget push to whoever a new todo was requested from.
    Silently no-ops if they have no subscription or VAPID isn't configured."""
    if todo.assigned_to_id is None:
        return
    subs = await get_subscriptions_for_user(db, todo.assigned_to_id)
    if not subs:
        return
    await push.send_to_subscriptions(
        db,
        subs,
        {
            "title": "New chore request",
            "body": f"{requested_by.display_name} asked you to: {todo.title}",
            "url": "/board",
        },
    )


async def send_weekly_nudge(db: AsyncSession) -> tuple[int, int, int]:
    """Pushes every non-break user who's below the weekly goal (or
    everyone, if no goal is set) a "log your points" nudge. Used by both
    the Admin panel's manual "send now" button and the automatic weekly
    schedule (household_service/scheduler.py) — either path stamps
    `last_nudge_sent_week` so the other one doesn't double-send the same
    week. Returns (notified, skipped_already_met_goal, skipped_no_subscription).
    Note this intentionally has nothing to send someone who's already hit
    their goal — if you just want to check push delivery works at all,
    use send_test_push instead (see /push/test)."""
    settings = await get_settings_row(db)
    week_start, _ = week_bounds(datetime.now(UTC).date(), settings.week_start_weekday)
    since = datetime.combine(week_start, time.min, tzinfo=UTC)
    users = await list_household_users(db)

    notified = 0
    already_met_goal = 0
    no_subscription = 0
    for user in users:
        if user.on_break:
            continue
        points = await points_for_user_since(db, user.id, since)
        if (
            settings.weekly_points_goal is not None
            and points >= settings.weekly_points_goal
        ):
            already_met_goal += 1
            continue
        subs = await get_subscriptions_for_user(db, user.id)
        if not subs:
            no_subscription += 1
            continue
        body = (
            f"You're at {points}/{settings.weekly_points_goal} points this week — "
            "don't forget your chores!"
            if settings.weekly_points_goal is not None
            else "Don't forget to log your points this week!"
        )
        sent = await push.send_to_subscriptions(
            db, subs, {"title": "Weekly reminder", "body": body, "url": "/home"}
        )
        if sent:
            notified += 1
        else:
            no_subscription += 1

    settings.last_nudge_sent_week = week_start.isoformat()
    await db.commit()
    return notified, already_met_goal, no_subscription


async def run_scheduled_nudge_if_due(db: AsyncSession) -> tuple[int, int, int] | None:
    """Called hourly by household_service.scheduler. Returns None (and
    does nothing) if the automatic schedule is off, it's not the
    configured weekday/hour right now, or this week's nudge already went
    out — otherwise runs it and returns send_weekly_nudge's result."""
    settings = await get_settings_row(db)
    if settings.nudge_weekday is None:
        return None
    now = datetime.now(UTC)
    if now.weekday() != settings.nudge_weekday or now.hour != settings.nudge_hour:
        return None
    week_start, _ = week_bounds(now.date(), settings.week_start_weekday)
    if settings.last_nudge_sent_week == week_start.isoformat():
        return None
    return await send_weekly_nudge(db)


async def send_test_push(db: AsyncSession, household_user_id: int) -> int:
    """Unconditional push to your own subscriptions — unlike
    send_weekly_nudge, this ignores break/goal status entirely, so it
    actually proves whether delivery works. Returns how many of your
    subscriptions reported success (0 means no subscription on this
    account, or delivery failed for all of them)."""
    subs = await get_subscriptions_for_user(db, household_user_id)
    if not subs:
        return 0
    return await push.send_to_subscriptions(
        db,
        subs,
        {
            "title": "Test notification",
            "body": "If you can see this, push notifications are working.",
            "url": "/settings",
        },
    )


def week_bounds(d: date, week_start: int) -> tuple[date, date]:
    """The Monday-Sunday-shaped week containing `d`, but starting on
    whatever weekday `week_start` names (0=Monday..6=Sunday, same
    convention as Task.weekdays) instead of being hardcoded to Monday.
    Every weekly computation in this service — points-this-week, the
    leaderboard's This/Last week filters, the heatmap, the balancer's
    weekly period, the nudge, auto-generated weekly reports — goes
    through this one function, so they all agree on where a week starts
    even after an admin changes HouseholdSettings.week_start_weekday."""
    start = d - timedelta(days=(d.weekday() - week_start) % 7)
    end = start + timedelta(days=6)
    return start, end


def _start_of_this_week(week_start: int) -> datetime:
    today = datetime.now(UTC).date()
    start, _ = week_bounds(today, week_start)
    return datetime.combine(start, time.min, tzinfo=UTC)


# ---- Reports ----------------------------------------------------------


def _resolve_period(
    period_type: ReportPeriod, period_date: date, week_start: int = 0
) -> tuple[date, date]:
    if period_type == ReportPeriod.week:
        return week_bounds(period_date, week_start)
    start = period_date.replace(day=1)
    last_day = calendar.monthrange(period_date.year, period_date.month)[1]
    end = period_date.replace(day=last_day)
    return start, end


async def create_report(
    db: AsyncSession, data: ReportCreate, generated_by: HouseholdUser | None
) -> Report:
    settings = await get_settings_row(db)
    start, end = _resolve_period(
        data.period_type, data.period_date, settings.week_start_weekday
    )
    since = datetime.combine(start, time.min, tzinfo=UTC)
    until = datetime.combine(end, time.max, tzinfo=UTC)

    rows = await leaderboard_for_period(db, since=since, until=until)

    report = Report(
        period_type=data.period_type,
        period_start=start,
        period_end=end,
        generated_by_id=generated_by.id if generated_by else None,
        file_path="",  # filled in below once we have the row's id
    )
    db.add(report)
    await db.flush()  # assigns report.id without committing yet

    filename = reports_pdf.generate_report_pdf(
        report_id=report.id,
        period_type=data.period_type.value,
        period_start=start,
        period_end=end,
        rows=[(user.display_name, total) for user, total in rows],
        rate=settings.points_to_money_rate,
        currency=settings.currency,
        generated_by=generated_by.display_name if generated_by else "Automatic",
        generated_at=datetime.now(UTC),
    )
    report.file_path = filename

    await db.commit()
    await db.refresh(report, attribute_names=["generated_by", "created_at"])
    return report


async def get_report_for_period(
    db: AsyncSession, period_type: ReportPeriod, start: date, end: date
) -> Report | None:
    result = await db.execute(
        select(Report).where(
            Report.period_type == period_type,
            Report.period_start == start,
            Report.period_end == end,
        )
    )
    return result.scalar_one_or_none()


async def list_reports(db: AsyncSession) -> list[Report]:
    result = await db.execute(
        select(Report)
        .options(selectinload(Report.generated_by))
        .order_by(Report.created_at.desc())
    )
    return list(result.scalars().all())


async def get_report(db: AsyncSession, report_id: int) -> Report | None:
    result = await db.execute(
        select(Report)
        .options(selectinload(Report.generated_by))
        .where(Report.id == report_id)
    )
    return result.scalar_one_or_none()


async def mark_report_paid(db: AsyncSession, report: Report, paid: bool) -> Report:
    report.paid_at = datetime.now(UTC) if paid else None
    await db.commit()
    await db.refresh(report, attribute_names=["paid_at"])
    return report


async def run_scheduled_auto_report_if_due(db: AsyncSession) -> Report | None:
    """Called hourly by household_service.scheduler. Not a weekday/hour
    match like the nudge — a "catch up" check instead: due whenever
    auto-generation is on and the most recently COMPLETED week (the one
    before the current one, which isn't over yet) hasn't had its report
    stamped yet. That means it still fires correctly even if the server
    was down right when the week rolled over, instead of silently
    missing that week forever. If an admin already generated that exact
    week's report manually, this just stamps it as done instead of
    generating a duplicate PDF."""
    settings = await get_settings_row(db)
    if not settings.auto_report_enabled:
        return None

    today = datetime.now(UTC).date()
    current_week_start, _ = week_bounds(today, settings.week_start_weekday)
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = current_week_start - timedelta(days=1)

    if settings.last_auto_report_period == last_week_start:
        return None

    report = await get_report_for_period(
        db, ReportPeriod.week, last_week_start, last_week_end
    )
    if report is None:
        report = await create_report(
            db,
            ReportCreate(period_type=ReportPeriod.week, period_date=last_week_start),
            generated_by=None,
        )
        await notify_new_report(db, report)

    settings.last_auto_report_period = last_week_start
    await db.commit()
    return report


async def notify_new_report(
    db: AsyncSession, report: Report, *, exclude_user_id: int | None = None
) -> None:
    """Reports (and the paid toggle) are admin-only, so only admins get
    notified — using the cached HouseholdUser.role hint (see main._self),
    since this service doesn't otherwise know who's an admin outside of a
    live request's own token. Skips whoever just generated it themselves
    (nothing to tell them they don't already know)."""
    users = await list_household_users(db)
    admins = [u for u in users if u.role == "admin" and u.id != exclude_user_id]
    if not admins:
        return
    body = f"{report.period_type.value.capitalize()} report ready: {report.period_start} – {report.period_end}"
    for admin in admins:
        subs = await get_subscriptions_for_user(db, admin.id)
        if not subs:
            continue
        await push.send_to_subscriptions(
            db,
            subs,
            {"title": "New report generated", "body": body, "url": "/admin"},
        )
