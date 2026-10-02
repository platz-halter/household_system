import calendar
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from household_service import push
from household_service import reports as reports_pdf
from household_service.models import (
    Category,
    HouseholdSettings,
    HouseholdUser,
    PointsEntry,
    PointsSource,
    PushSubscription,
    Report,
    ReportPeriod,
    Task,
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
    settings.points_to_eur_rate = data.points_to_eur_rate
    settings.nudge_weekday = data.nudge_weekday
    settings.nudge_hour = data.nudge_hour
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
            "url": "#/board",
        },
    )


async def send_weekly_nudge(db: AsyncSession) -> tuple[int, int]:
    """Pushes every non-break user who's below the weekly goal (or
    everyone, if no goal is set) a "log your points" nudge. Used by both
    the Admin panel's manual "send now" button and the automatic weekly
    schedule (household_service/scheduler.py) — either path stamps
    `last_nudge_sent_week` so the other one doesn't double-send the same
    week. Returns (notified, skipped_no_subscription)."""
    since = _start_of_this_week()
    settings = await get_settings_row(db)
    users = await list_household_users(db)

    notified = 0
    skipped = 0
    for user in users:
        if user.on_break:
            continue
        points = await points_for_user_since(db, user.id, since)
        if (
            settings.weekly_points_goal is not None
            and points >= settings.weekly_points_goal
        ):
            continue
        subs = await get_subscriptions_for_user(db, user.id)
        if not subs:
            skipped += 1
            continue
        body = (
            f"You're at {points}/{settings.weekly_points_goal} points this week — "
            "don't forget your chores!"
            if settings.weekly_points_goal is not None
            else "Don't forget to log your points this week!"
        )
        sent = await push.send_to_subscriptions(
            db, subs, {"title": "Weekly reminder", "body": body, "url": "#/home"}
        )
        if sent:
            notified += 1
        else:
            skipped += 1

    settings.last_nudge_sent_week = _iso_week_key(datetime.now(UTC))
    await db.commit()
    return notified, skipped


async def run_scheduled_nudge_if_due(db: AsyncSession) -> tuple[int, int] | None:
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
    if settings.last_nudge_sent_week == _iso_week_key(now):
        return None
    return await send_weekly_nudge(db)


def _iso_week_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _start_of_this_week() -> datetime:
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday, time.min, tzinfo=UTC)


# ---- Reports ----------------------------------------------------------


def _resolve_period(period_type: ReportPeriod, period_date: date) -> tuple[date, date]:
    if period_type == ReportPeriod.week:
        start = period_date - timedelta(days=period_date.weekday())
        end = start + timedelta(days=6)
    else:
        start = period_date.replace(day=1)
        last_day = calendar.monthrange(period_date.year, period_date.month)[1]
        end = period_date.replace(day=last_day)
    return start, end


async def create_report(
    db: AsyncSession, data: ReportCreate, generated_by: HouseholdUser
) -> Report:
    start, end = _resolve_period(data.period_type, data.period_date)
    since = datetime.combine(start, time.min, tzinfo=UTC)
    until = datetime.combine(end, time.max, tzinfo=UTC)

    rows = await leaderboard_for_period(db, since=since, until=until)
    settings = await get_settings_row(db)

    report = Report(
        period_type=data.period_type,
        period_start=start,
        period_end=end,
        generated_by_id=generated_by.id,
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
        eur_rate=settings.points_to_eur_rate,
        generated_by=generated_by.display_name,
        generated_at=datetime.now(UTC),
    )
    report.file_path = filename

    await db.commit()
    await db.refresh(report, attribute_names=["generated_by", "created_at"])
    return report


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
