import calendar
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, func, or_, select, update
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
    TakeoverRequest,
    TakeoverStatus,
    Task,
    TaskAssignment,
    TaskChainLink,
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
    zero out, what's left). Also cancels any pending takeover request
    this now-affects: one this user sent as requester (their deleted/
    unassigned item's assignment is gone, cascading automatically for
    the TaskAssignment case — see the model's FK), and any where this
    user was the TARGET (can't accept a takeover while on break)."""
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
    released_todo_ids = []
    for todo in todos_result.scalars().all():
        todo.assigned_to_id = None
        released_todo_ids.append(todo.id)

    now = datetime.now(UTC)
    await db.execute(
        update(TakeoverRequest)
        .where(
            TakeoverRequest.target_id == user.id,
            TakeoverRequest.status == TakeoverStatus.pending,
        )
        .values(status=TakeoverStatus.cancelled, responded_at=now)
    )
    if released_todo_ids:
        await db.execute(
            update(TakeoverRequest)
            .where(
                TakeoverRequest.todo_item_id.in_(released_todo_ids),
                TakeoverRequest.status == TakeoverStatus.pending,
            )
            .values(status=TakeoverStatus.cancelled, responded_at=now)
        )


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


# ---- Chain tasks ----------------------------------------------------------


async def chain_child_task_ids(db: AsyncSession) -> set[int]:
    """Every task id that's a chain child of something — i.e. `TaskOut
    .is_chain_child` for the whole task list in one query, and what the
    sweep/Home/direct-completion all exclude on. See TaskChainLink's own
    docstring for why this is derived from the link table on every call
    rather than cached on Task itself."""
    result = await db.execute(select(TaskChainLink.child_task_id).distinct())
    return {row[0] for row in result.all()}


async def is_chain_child(db: AsyncSession, task_id: int) -> bool:
    result = await db.execute(
        select(TaskChainLink.id).where(TaskChainLink.child_task_id == task_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_chain_links(
    db: AsyncSession, parent_task_id: int
) -> list[TaskChainLink]:
    result = await db.execute(
        select(TaskChainLink)
        .where(TaskChainLink.parent_task_id == parent_task_id)
        .options(selectinload(TaskChainLink.child_task))
        .order_by(TaskChainLink.position)
    )
    return list(result.scalars().all())


async def get_chain_link(db: AsyncSession, link_id: int) -> TaskChainLink | None:
    result = await db.execute(
        select(TaskChainLink)
        .where(TaskChainLink.id == link_id)
        .options(selectinload(TaskChainLink.child_task))
    )
    return result.scalar_one_or_none()


async def list_chain_parents(
    db: AsyncSession, child_task_id: int
) -> list[TaskChainLink]:
    """The reverse of list_chain_links: every link where `child_task_id`
    is the CHILD — i.e. which task(s) chain it, for the "already
    chained, complete it directly anyway?" confirm (see complete_task's
    `force` and TaskCompleteRequest). A task is usually only
    someone's chain child once, but nothing stops it being chained from
    more than one parent, so this is a list, not a single link."""
    result = await db.execute(
        select(TaskChainLink)
        .where(TaskChainLink.child_task_id == child_task_id)
        .options(selectinload(TaskChainLink.parent_task))
        .order_by(TaskChainLink.position)
    )
    return list(result.scalars().all())


async def _reachable_task_ids(db: AsyncSession, start_task_id: int) -> set[int]:
    """Every task reachable from `start_task_id` by following existing
    chain links downward (start's children, their children, ...) —
    everything a cycle check needs to know "is already a descendant of
    this task." Walks the whole link table in the worst case, which is
    fine at this project's scale (a household's task list, not a graph
    database) — correctness over a cleverer single query."""
    seen: set[int] = set()
    frontier = [start_task_id]
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        result = await db.execute(
            select(TaskChainLink.child_task_id).where(
                TaskChainLink.parent_task_id == current
            )
        )
        frontier.extend(row[0] for row in result.all())
    seen.discard(start_task_id)
    return seen


async def create_chain_link(
    db: AsyncSession, *, parent_task_id: int, child_task_id: int, same_user: bool
) -> TaskChainLink:
    if parent_task_id == child_task_id:
        raise ValueError("A task can't be chained to itself")
    if await get_task(db, parent_task_id) is None:
        raise ValueError(f"Unknown task id: {parent_task_id}")
    if await get_task(db, child_task_id) is None:
        raise ValueError(f"Unknown task id: {child_task_id}")

    existing = await db.scalar(
        select(TaskChainLink.id).where(
            TaskChainLink.parent_task_id == parent_task_id,
            TaskChainLink.child_task_id == child_task_id,
        )
    )
    if existing is not None:
        raise ValueError("This chain link already exists")

    # Adding parent->child only closes a cycle if parent is already
    # reachable FROM child (child -> ... -> parent already exists) —
    # that would make parent a descendant of its own new child.
    if parent_task_id in await _reachable_task_ids(db, child_task_id):
        raise ValueError("This would create a cycle of chained tasks")

    max_position = await db.scalar(
        select(func.max(TaskChainLink.position)).where(
            TaskChainLink.parent_task_id == parent_task_id
        )
    )
    link = TaskChainLink(
        parent_task_id=parent_task_id,
        child_task_id=child_task_id,
        same_user=same_user,
        position=(max_position or 0) + 1,
    )
    db.add(link)

    # A task that becomes a chain child has exactly one legitimate
    # source of instances from now on — drop any TaskAssignment it's
    # currently holding, so the sweep's existing (now orphaned-in-intent)
    # assignment can't coexist with chain-spawned todos for the same
    # task. Its own points history is untouched; this only clears a
    # forward-looking recurring assignment.
    await db.execute(
        delete(TaskAssignment).where(TaskAssignment.task_id == child_task_id)
    )

    await db.commit()
    await db.refresh(link, attribute_names=["child_task", "parent_task"])
    return link


async def delete_chain_link(db: AsyncSession, link: TaskChainLink) -> None:
    await db.delete(link)
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
    db: AsyncSession, task: Task, user: HouseholdUser, *, force: bool = False
) -> PointsEntry:
    """Logs one completion of `task` by `user` and awards points, including
    the configured ramp-up bonus if this user is (so far) the only one who
    has ever completed this task. Rejects a completion past the task's own
    `times_per_day` for today (by anyone, not just this user) — without
    this, a 1x/day task never actually went away, and repeated taps just
    kept awarding points indefinitely.

    Also rejects a task that only exists as someone else's chain child
    (see TaskChainLink) — it has no legitimate direct occurrence of its
    own; it's normally completed via the todo it's spawned as instead.
    `force=True` overrides this one check (and only this one) — the
    frontend confirms this explicitly first, naming which task(s) chain
    it (see crud.list_chain_parents / GET /tasks/{id}/chain-parents),
    so this is an informed override, not a silent bypass. It doesn't
    touch any already-spawned, still-open todo for the same chain link
    — completing both would double-count that occurrence, but that's
    the same kind of judgment call `times_per_day` already leaves to
    the person tapping complete, not something this function can
    second-guess."""
    if await is_chain_child(db, task.id) and not force:
        raise ValueError(
            f'"{task.name}" is a chained task — complete it from the todo '
            "it's spawned as, not directly"
        )
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
    await db.flush()
    to_notify = await _spawn_chain_children(
        db, parent_task_id=task.id, entry=entry, completer=user
    )
    await db.commit()
    await db.refresh(
        entry, attribute_names=["household_user", "task", "todo_item", "earned_at"]
    )
    for child in to_notify:
        await notify_todo_assigned(db, child, user)
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
        selectinload(TodoItem.chain_link).selectinload(TaskChainLink.parent_task),
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


async def _check_assignable(db: AsyncSession, target_id: int) -> HouseholdUser:
    """Shared guard for anything that hands work to a specific person —
    creating/editing a todo with an assignee, an admin reassign, or a
    takeover request. Raises ValueError (routes turn these into 400s)
    rather than silently assigning to someone who's on break and not
    expected to be doing anything right now (see PROJECT_SPEC.md)."""
    target = await get_household_user(db, target_id)
    if target is None:
        raise ValueError(f"Unknown household user id: {target_id}")
    if target.on_break:
        raise ValueError(f"{target.display_name} is on break")
    return target


async def _cancel_pending_takeover_for_todo(db: AsyncSession, todo_id: int) -> None:
    """A pending takeover request only makes sense while its requester
    still holds the item — called wherever that stops being true
    (reassigned, completed, cancelled) other than by the requester
    going on break, which cleans up via _release_user_assignments."""
    await db.execute(
        update(TakeoverRequest)
        .where(
            TakeoverRequest.todo_item_id == todo_id,
            TakeoverRequest.status == TakeoverStatus.pending,
        )
        .values(status=TakeoverStatus.cancelled, responded_at=datetime.now(UTC))
    )


async def create_todo(
    db: AsyncSession, data: TodoCreate, creator: HouseholdUser
) -> TodoItem:
    if data.assigned_to_id is not None:
        await _check_assignable(db, data.assigned_to_id)
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
        await _check_assignable(db, data.assigned_to_id)
        todo.assigned_to_id = data.assigned_to_id
    await db.commit()
    await db.refresh(
        todo, attribute_names=["created_by", "assigned_to", "completed_by"]
    )
    return todo


async def reassign_todo(
    db: AsyncSession, todo: TodoItem, new_assignee_id: int
) -> TodoItem:
    """Admin-only direct handoff of an open board item — unlike a
    takeover request, no acceptance needed (see TodoReassignIn). Still
    respects `exclude_user_id` (see TodoItem's own docstring): a chain
    todo's "not the completer" exclusion is a fairness rule the admin
    override shouldn't quietly undo. Cancels any pending takeover
    request on this item, since its "requester currently holds this"
    assumption is now stale."""
    if todo.status != TodoStatus.open:
        raise ValueError(f"Can't reassign a todo that's already {todo.status.value}")
    target = await _check_assignable(db, new_assignee_id)
    if todo.exclude_user_id is not None and target.id == todo.exclude_user_id:
        raise ValueError(f"{target.display_name} can't be assigned this item")
    todo.assigned_to_id = target.id
    await _cancel_pending_takeover_for_todo(db, todo.id)
    await db.commit()
    await db.refresh(todo, attribute_names=["assigned_to"])
    return todo


async def complete_todo(
    db: AsyncSession, todo: TodoItem, user: HouseholdUser
) -> TodoItem:
    """Completes `todo` and awards its points. If `todo` is itself a
    chain-spawned instance (todo.chain_link_id set), also spawns the
    NEXT level of the chain — the task it represents is
    `chain_link.child_task_id`, not a Task row this TodoItem points to
    directly, so that's what's used as the new parent (multi-level
    chains, see TaskChainLink)."""
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
    await db.flush()
    await _cancel_pending_takeover_for_todo(db, todo.id)
    to_notify: list[TodoItem] = []
    if todo.chain_link_id is not None:
        link = await db.get(TaskChainLink, todo.chain_link_id)
        if link is not None:
            to_notify = await _spawn_chain_children(
                db, parent_task_id=link.child_task_id, entry=entry, completer=user
            )
    await db.commit()
    await db.refresh(todo, attribute_names=["completed_by", "completed_at", "status"])
    for child in to_notify:
        await notify_todo_assigned(db, child, user)
    return todo


async def cancel_todo(db: AsyncSession, todo: TodoItem) -> TodoItem:
    todo.status = TodoStatus.cancelled
    await _cancel_pending_takeover_for_todo(db, todo.id)
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
    rowcount 0 and the caller turns that into a 409. Also blocks
    whoever a "different person" chain spawn explicitly excluded (see
    TodoItem.exclude_user_id) from just claiming their way around that
    exclusion themselves."""
    result = await db.execute(
        update(TodoItem)
        .where(
            TodoItem.id == todo_id,
            TodoItem.status == TodoStatus.open,
            TodoItem.assigned_to_id.is_(None),
            or_(
                TodoItem.exclude_user_id.is_(None),
                TodoItem.exclude_user_id != user.id,
            ),
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


async def _gather_balancer_load(
    db: AsyncSession,
    eligible: list[HouseholdUser],
    as_of: date,
    week_start: date,
) -> tuple[
    dict[int, int],
    dict[int, int],
    dict[int, int],
    list[TaskAssignment],
    dict[int, int],
]:
    """Seeds load_points/load_count/points_this_week for every eligible
    user from whatever they're already carrying into `as_of` — the same
    "what does today's picture look like" snapshot run_balancing's sweep
    starts from, pulled out here so a single immediate chain-todo
    assignment (_assign_chain_todo_now) can use the identical fairness
    picture without waiting for the next scheduled run. Also hands back
    current_assignments/remaining_by_assignment, since run_balancing's
    own sweep and rebalance passes need those same two values again."""
    eligible_by_id = {u.id: u for u in eligible}

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
    return (
        load_points,
        load_count,
        points_this_week,
        current_assignments,
        remaining_by_assignment,
    )


def _is_eligible_for_tasks(user: HouseholdUser) -> bool:
    """Whether `user` should ever be handed new work by the balancer's
    sweep/rebalance or chain-task auto-assignment — not on break, and
    not a viewer. Viewers can never complete anything themselves
    (`complete_task`/`complete_todo` are `can_write`-gated), so handing
    one something just leaves it permanently stuck; `role` is only a
    cached hint (see HouseholdUser's own docstring), but good enough
    here, same as `crud.leaderboard()`'s viewer exclusion and
    `_validate_takeover_target`'s."""
    return not user.on_break and user.role != "viewer"


async def _assign_chain_todo_now(
    db: AsyncSession, todo: TodoItem, *, exclude_user_id: int
) -> None:
    """Immediately assigns a freshly-spawned "different person" chain
    child to whoever's currently least loaded, using the exact same
    fairness picture run_balancing's sweep uses — just invoked for this
    one todo right now instead of waiting for the next scheduled run (a
    once-a-day cadence would otherwise leave a same-day chain todo
    unassigned for hours). Never assigns to `exclude_user_id` (whoever
    completed the parent). Left open/unassigned if nobody else is
    eligible — exactly like an ordinary sweep leftover, and still
    excluded from self-claiming (see claim_todo)."""
    as_of = datetime.now(UTC).date()
    all_users = await list_household_users(db)
    eligible = [u for u in all_users if _is_eligible_for_tasks(u)]
    if not eligible:
        return

    settings = await get_settings_row(db)
    week_start, _week_end = _resolve_period(
        ReportPeriod.week, as_of, settings.week_start_weekday
    )
    (
        load_points,
        load_count,
        points_this_week,
        _current,
        _remaining,
    ) = await _gather_balancer_load(db, eligible, as_of, week_start)

    balancing_users = [
        balancing.EligibleUser(
            user_id=u.id,
            points_this_week=points_this_week[u.id],
            already_assigned_points=load_points[u.id],
            already_assigned_count=load_count[u.id],
        )
        for u in eligible
    ]
    # Must exceed everyone's current count — this call is only ever
    # handing out ONE item, but balance()'s cap filter is
    # `count[uid] < max_new_items_per_user`, so anyone already sitting
    # at whatever cap we pick would be wrongly skipped even though
    # they're the fairest (or only) choice for this single item.
    max_new_items_per_user = max(load_count.values(), default=0) + 1
    result = balancing.balance(
        users=balancing_users,
        tasks=[],
        todos=[
            balancing.CandidateTodo(
                todo_id=todo.id, points=todo.points, excluded_user_id=exclude_user_id
            )
        ],
        max_new_items_per_user=max_new_items_per_user,
    )
    picked = result.todo_assignments.get(todo.id)
    if picked is not None:
        todo.assigned_to_id = picked


async def _spawn_chain_children(
    db: AsyncSession,
    *,
    parent_task_id: int,
    entry: PointsEntry,
    completer: HouseholdUser,
) -> list[TodoItem]:
    """Spawns one TodoItem per chain link hanging off `parent_task_id`,
    for the occurrence just logged as `entry`. Must run in the same
    transaction as `entry`'s own flush (the caller flushes first so
    entry.id exists, then commits once after this returns) — a crash
    between the two can never leave points awarded with no matching
    children, or vice versa. Idempotent via uq_todo_chain_spawn
    (chain_link_id, spawned_by_entry_id) if this is ever retried for the
    same entry.

    Returns the different-person children that got assigned, for the
    caller to push-notify AFTER its own final commit —
    push.send_to_subscriptions commits internally (it prunes dead
    subscriptions as it goes), so notifying from inside this function,
    before the caller's commit, would split one logical transaction
    (points entry + all spawned children) into several."""
    to_notify: list[TodoItem] = []
    links = await list_chain_links(db, parent_task_id)
    for link in links:
        child = TodoItem(
            title=link.child_task.name,
            description=link.child_task.description,
            points=link.child_task.points,
            due_date=datetime.now(UTC).date(),
            created_by_id=completer.id,
            chain_link_id=link.id,
            spawned_by_entry_id=entry.id,
        )
        if link.same_user:
            # Direct assignment, bypassing the balancer entirely — this
            # is "the same person does both," not a fairness decision.
            child.assigned_to_id = completer.id
            db.add(child)
            await db.flush()
        else:
            child.exclude_user_id = completer.id
            db.add(child)
            await db.flush()
            await _assign_chain_todo_now(db, child, exclude_user_id=completer.id)
            if child.assigned_to_id is not None:
                to_notify.append(child)
    return to_notify


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
    eligible = [u for u in all_users if _is_eligible_for_tasks(u)]
    eligible_by_id = {u.id: u for u in eligible}

    settings.last_balance_run = as_of

    # No early-return for "nobody eligible" — fall through to the normal
    # path so candidates still get counted (balancing.balance() returns
    # everything as unassigned when `users` is empty), which is what
    # makes unassigned_task_count/unassigned_todo_count mean something
    # real in that case instead of silently reading 0/0.

    # ---- seed everyone's starting load for this run --------------------
    (
        load_points,
        load_count,
        points_this_week,
        current_assignments,
        remaining_by_assignment,
    ) = await _gather_balancer_load(db, eligible, as_of, week_start)
    assignment_by_id = {a.id: a for a in current_assignments}

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
    excluded_chain_child_ids = await chain_child_task_ids(db)
    for task in tasks_result.scalars().all():
        if task.id in excluded_chain_child_ids:
            # Has exactly one source of instances — whatever chain
            # spawns it — so the sweep must never also hand it out.
            continue
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
        balancing.CandidateTodo(
            todo_id=t.id, points=t.points, excluded_user_id=t.exclude_user_id
        )
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

    if reassignments:
        # The rebalance pass just moved these away from whoever held
        # them — any pending takeover request asking someone ELSE to
        # take one over is now asking about an assignment that holder
        # doesn't have anymore.
        await db.execute(
            update(TakeoverRequest)
            .where(
                TakeoverRequest.task_assignment_id.in_(
                    [row.id for row, *_ in reassignments]
                ),
                TakeoverRequest.status == TakeoverStatus.pending,
            )
            .values(status=TakeoverStatus.cancelled, responded_at=now)
        )

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


# ---- Takeover requests ---------------------------------------------------


async def get_task_assignment(
    db: AsyncSession, assignment_id: int
) -> TaskAssignment | None:
    result = await db.execute(
        select(TaskAssignment)
        .options(
            selectinload(TaskAssignment.task),
            selectinload(TaskAssignment.household_user),
        )
        .where(TaskAssignment.id == assignment_id)
    )
    return result.scalar_one_or_none()


def _takeover_query():
    return select(TakeoverRequest).options(
        selectinload(TakeoverRequest.requester),
        selectinload(TakeoverRequest.target),
        selectinload(TakeoverRequest.todo_item),
        selectinload(TakeoverRequest.task_assignment).selectinload(TaskAssignment.task),
    )


async def get_takeover_request(
    db: AsyncSession, request_id: int
) -> TakeoverRequest | None:
    result = await db.execute(_takeover_query().where(TakeoverRequest.id == request_id))
    return result.scalar_one_or_none()


async def list_takeover_requests(
    db: AsyncSession, user_id: int, *, direction: str
) -> list[TakeoverRequest]:
    """`direction` is "incoming" (requests asking this user to take
    something over) or "outgoing" (requests this user sent). Only the
    still-actionable ones (pending) — once resolved, a request isn't
    surfaced anywhere, same as this app keeps no general notifications
    inbox."""
    column = (
        TakeoverRequest.target_id
        if direction == "incoming"
        else TakeoverRequest.requester_id
    )
    result = await db.execute(
        _takeover_query()
        .where(column == user_id, TakeoverRequest.status == TakeoverStatus.pending)
        .order_by(TakeoverRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def _validate_takeover_target(
    db: AsyncSession,
    requester: HouseholdUser,
    target_id: int,
    *,
    exclude_user_id: int | None = None,
) -> HouseholdUser:
    if target_id == requester.id:
        raise ValueError("Can't ask yourself to take over")
    target = await _check_assignable(db, target_id)
    # `role` is only a cached hint (see HouseholdUser's own docstring),
    # but good enough here: a viewer can't call accept (can_write-gated)
    # anyway, so without this the request would just dead-end pending
    # forever instead of failing clearly at creation time.
    if target.role == "viewer":
        raise ValueError(f"{target.display_name} is a viewer and can't take over tasks")
    if exclude_user_id is not None and target.id == exclude_user_id:
        raise ValueError(f"{target.display_name} can't take over this item")
    return target


async def create_takeover_request_for_todo(
    db: AsyncSession, todo: TodoItem, requester: HouseholdUser, target_id: int
) -> TakeoverRequest:
    if todo.assigned_to_id != requester.id:
        raise ValueError("You don't currently hold this item")
    if todo.status != TodoStatus.open:
        raise ValueError(f"Can't hand over a todo that's already {todo.status.value}")
    target = await _validate_takeover_target(
        db, requester, target_id, exclude_user_id=todo.exclude_user_id
    )
    existing = await db.scalar(
        select(TakeoverRequest.id).where(
            TakeoverRequest.todo_item_id == todo.id,
            TakeoverRequest.status == TakeoverStatus.pending,
        )
    )
    if existing is not None:
        raise ValueError("A takeover request is already pending for this item")
    req = TakeoverRequest(
        requester_id=requester.id, target_id=target.id, todo_item_id=todo.id
    )
    db.add(req)
    await db.commit()
    return await get_takeover_request(db, req.id)


async def create_takeover_request_for_assignment(
    db: AsyncSession,
    assignment: TaskAssignment,
    requester: HouseholdUser,
    target_id: int,
) -> TakeoverRequest:
    if assignment.household_user_id != requester.id:
        raise ValueError("You don't currently hold this assignment")
    target = await _validate_takeover_target(db, requester, target_id)
    existing = await db.scalar(
        select(TakeoverRequest.id).where(
            TakeoverRequest.task_assignment_id == assignment.id,
            TakeoverRequest.status == TakeoverStatus.pending,
        )
    )
    if existing is not None:
        raise ValueError("A takeover request is already pending for this assignment")
    req = TakeoverRequest(
        requester_id=requester.id, target_id=target.id, task_assignment_id=assignment.id
    )
    db.add(req)
    await db.commit()
    return await get_takeover_request(db, req.id)


async def accept_takeover_request(
    db: AsyncSession, req: TakeoverRequest
) -> TakeoverRequest:
    """Hands the item to the target. Re-validates the requester still
    holds it with a conditional UPDATE — same reasoning as claim_todo's:
    the holder can change out from under a pending request (an admin
    reassign, the balancer's rebalance pass, or the requester going on
    break — though the latter two already cancel the request outright,
    see run_balancing/_release_user_assignments) between the ask and
    the answer. Raises ValueError if that race is lost; the request is
    marked cancelled rather than left dangling in `pending`."""
    now = datetime.now(UTC)
    if req.todo_item_id is not None:
        result = await db.execute(
            update(TodoItem)
            .where(
                TodoItem.id == req.todo_item_id,
                TodoItem.assigned_to_id == req.requester_id,
                TodoItem.status == TodoStatus.open,
            )
            .values(assigned_to_id=req.target_id)
        )
    else:
        result = await db.execute(
            update(TaskAssignment)
            .where(
                TaskAssignment.id == req.task_assignment_id,
                TaskAssignment.household_user_id == req.requester_id,
            )
            .values(household_user_id=req.target_id, reassigned_at=now)
        )
    if result.rowcount == 0:
        req.status = TakeoverStatus.cancelled
        req.responded_at = now
        await db.commit()
        raise ValueError("This item changed hands before the request could be accepted")
    req.status = TakeoverStatus.accepted
    req.responded_at = now
    await db.commit()
    return await get_takeover_request(db, req.id)


async def decline_takeover_request(
    db: AsyncSession, req: TakeoverRequest
) -> TakeoverRequest:
    req.status = TakeoverStatus.declined
    req.responded_at = datetime.now(UTC)
    await db.commit()
    return await get_takeover_request(db, req.id)


async def cancel_takeover_request(
    db: AsyncSession, req: TakeoverRequest
) -> TakeoverRequest:
    req.status = TakeoverStatus.cancelled
    req.responded_at = datetime.now(UTC)
    await db.commit()
    return await get_takeover_request(db, req.id)


def _takeover_item_label(req: TakeoverRequest) -> str:
    return req.todo_item.title if req.todo_item else req.task_assignment.task.name


async def notify_takeover_requested(db: AsyncSession, req: TakeoverRequest) -> None:
    """Fire-and-forget push to the target when someone asks them to
    take something over. Called by the route AFTER create_takeover_
    request_for_* already committed — push.send_to_subscriptions commits
    internally, so calling it mid-transaction would split one logical
    write into several (see _spawn_chain_children's own note)."""
    subs = await get_subscriptions_for_user(db, req.target_id)
    if not subs:
        return
    await push.send_to_subscriptions(
        db,
        subs,
        {
            "title": "Takeover request",
            "body": f"{req.requester.display_name} asked you to take over: "
            f"{_takeover_item_label(req)}",
            "url": "/home",
        },
    )


async def notify_takeover_responded(db: AsyncSession, req: TakeoverRequest) -> None:
    """Fire-and-forget push to the requester once the target answers.
    Same after-commit timing as notify_takeover_requested."""
    subs = await get_subscriptions_for_user(db, req.requester_id)
    if not subs:
        return
    verb = "accepted" if req.status == TakeoverStatus.accepted else "declined"
    await push.send_to_subscriptions(
        db,
        subs,
        {
            "title": f"Takeover request {verb}",
            "body": f"{req.target.display_name} {verb} your request for: "
            f"{_takeover_item_label(req)}",
            "url": "/home",
        },
    )


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
