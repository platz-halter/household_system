from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from household_service.models import (
    Category,
    HouseholdSettings,
    HouseholdUser,
    PointsEntry,
    PointsSource,
    Task,
    TodoItem,
    TodoStatus,
)
from household_service.schemas import (
    CategoryIn,
    CategoryUpdate,
    HouseholdSettingsUpdate,
    HouseholdUserUpdate,
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
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.on_break is not None:
        user.on_break = data.on_break
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
    if data.weekdays is not None:
        task.weekdays = data.weekdays
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


async def complete_task(
    db: AsyncSession, task: Task, user: HouseholdUser
) -> PointsEntry:
    """Logs one completion of `task` by `user` and awards points, including
    the configured ramp-up bonus if this user is (so far) the only one who
    has ever completed this task."""
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
    await db.refresh(entry, attribute_names=["household_user", "earned_at"])
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


# ---- Points -------------------------------------------------------------


def _points_entry_query():
    return select(PointsEntry).options(selectinload(PointsEntry.household_user))


async def recent_points(db: AsyncSession, limit: int = 20) -> list[PointsEntry]:
    result = await db.execute(
        _points_entry_query().order_by(PointsEntry.earned_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def leaderboard(
    db: AsyncSession, *, since: datetime | None = None, until: datetime | None = None
) -> list[tuple[HouseholdUser, int]]:
    """Total points per non-break user, highest first. Users on break are
    excluded entirely (not just zeroed) per the break-mode spec. Users with
    no completions in range still appear, with a total of 0."""
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
        .where(HouseholdUser.on_break.is_(False))
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
    await db.commit()
    await db.refresh(settings)
    return settings
