import calendar
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from household_service import balancing, push
from household_service import reports as reports_pdf
from household_service.i18n import t

logger = logging.getLogger(__name__)
from household_service.models import (
    Category,
    EventGroup,
    EventGroupExclusion,
    EventGroupRun,
    EventGroupTask,
    HouseholdSettings,
    HouseholdUser,
    Notification,
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
    EventGroupIn,
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
    # The admin-configured default at the moment this person is first
    # seen — not retroactive, so changing it later never affects anyone
    # already in the table (see HouseholdSettings.default_language).
    settings = await get_settings_row(db)
    user = HouseholdUser(
        subject=subject,
        display_name=subject,
        preferred_language=settings.default_language,
    )
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


async def update_my_language(
    db: AsyncSession, user: HouseholdUser, language: str
) -> HouseholdUser:
    """Separate from update_household_user/PATCH /me on purpose — this
    one is can_read-gated (see main.update_my_language) so a viewer can
    switch their own UI language too, unlike display_name/on_break,
    which have no legitimate reason for a read-only account to touch."""
    user.preferred_language = language
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
    user was the TARGET (can't accept a takeover while on break).

    "Today" is the household's own configured local calendar day
    (HouseholdSettings.timezone), matching run_balancing's own period
    boundaries — otherwise a period a UTC-anchored "today" considers
    already-ended could still be the household's current local period,
    or vice versa, right around the UTC day boundary."""
    settings = await get_settings_row(db)
    today = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
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
    return select(Task).options(
        selectinload(Task.categories), selectinload(Task.pinned_user)
    )


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


async def _validate_pinned_user(db: AsyncSession, pinned_user_id: int | None) -> None:
    """A task's "always assign to" owner must be a real, non-viewer
    household user — a viewer can never complete anything (can_write-
    gated), so pinning one would leave the task permanently stuck, same
    reasoning as _is_eligible_for_tasks' own viewer exclusion."""
    if pinned_user_id is None:
        return
    pinned_user = await db.get(HouseholdUser, pinned_user_id)
    if pinned_user is None:
        raise ValueError(f"Unknown pinned user id: {pinned_user_id}")
    if pinned_user.role == "viewer":
        raise ValueError("a viewer can't be pinned to a task — they can never complete it")


async def create_task(db: AsyncSession, data: TaskCreate) -> Task:
    categories = await _resolve_categories(db, data.category_ids)
    await _validate_pinned_user(db, data.pinned_user_id)
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
        pinned_user_id=data.pinned_user_id,
        categories=categories,
    )
    db.add(task)
    await db.commit()
    await db.refresh(
        task, attribute_names=["categories", "pinned_user", "created_at", "updated_at"]
    )
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
    # "pinned_user_id" in model_fields_set, not `is not None` — unlike
    # every other field here, explicit null has to be distinguishable
    # from "not included in this PATCH," since clearing an existing pin
    # is a real, expected action (see TaskUpdate's own docstring).
    if "pinned_user_id" in data.model_fields_set:
        await _validate_pinned_user(db, data.pinned_user_id)
        task.pinned_user_id = data.pinned_user_id
    await db.commit()
    await db.refresh(task, attribute_names=["categories", "pinned_user", "updated_at"])
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


async def is_chain_parent(db: AsyncSession, task_id: int) -> bool:
    """Whether `task_id` already chains at least one other task — the
    other half of the one-level cap (see create_chain_link): a task
    that's about to become someone's chain CHILD must not already be
    a parent itself, or it'd sit in the middle of a two-level chain."""
    result = await db.execute(
        select(TaskChainLink.id).where(TaskChainLink.parent_task_id == task_id).limit(1)
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

    # Chains are capped at exactly one level: a task is a pure parent, a
    # pure child, or neither — never both. This is what makes a chained
    # loop structurally impossible, not a graph walk looking for one: a
    # cycle needs at least one task with both an incoming and an
    # outgoing chain edge, and these three checks together mean no task
    # can ever have both, from either direction:
    #   - the new PARENT can't already be a CHILD (would make it a
    #     middle node, child-side)
    #   - the new CHILD can't already be a PARENT (would make it a
    #     middle node, parent-side — the case a two-check version of
    #     this missed: C->A->B is still only "A is already a child" or
    #     "A is already a parent" depending which link you look at
    #     first, so both directions have to be checked on BOTH tasks)
    #   - the new CHILD can't already be a CHILD of something else
    #     (no double-parenting)
    if await is_chain_child(db, parent_task_id):
        raise ValueError(
            "This task is already chained from another task and can't "
            "chain further tasks itself"
        )
    if await is_chain_parent(db, child_task_id):
        raise ValueError(
            "This task already chains another task and can't be chained itself"
        )
    if await is_chain_child(db, child_task_id):
        raise ValueError("This task is already chained to another task")

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


# ---- Event groups ---------------------------------------------------------


def _event_group_query():
    return select(EventGroup).options(
        selectinload(EventGroup.roots).selectinload(EventGroupTask.task),
        selectinload(EventGroup.exclusions),
    )


async def list_event_groups(db: AsyncSession) -> list[EventGroup]:
    result = await db.execute(_event_group_query().order_by(EventGroup.name))
    return list(result.scalars().unique().all())


async def get_event_group(db: AsyncSession, group_id: int) -> EventGroup | None:
    result = await db.execute(_event_group_query().where(EventGroup.id == group_id))
    return result.scalar_one_or_none()


async def _validate_event_group_roots(db: AsyncSession, task_ids: list[int]) -> None:
    """A root must be a real, active, independently-schedulable task —
    the same "one source of instances" reasoning that already excludes
    a chain-child task from direct completion and the balancer's sweep
    applies here too: letting an already-chained task also be a group
    root would give it a second, independent way to spawn instances."""
    for task_id in task_ids:
        task = await get_task(db, task_id)
        if task is None:
            raise ValueError(f"Unknown task id: {task_id}")
        if not task.active:
            raise ValueError(
                f'"{task.name}" is inactive and can\'t be in an event group'
            )
        if await is_chain_child(db, task_id):
            raise ValueError(
                f'"{task.name}" is already a chain task and can\'t also be an '
                "event group root — chain it from one of the group's roots instead"
            )


async def create_event_group(db: AsyncSession, data: EventGroupIn) -> EventGroup:
    existing = await db.scalar(
        select(EventGroup.id).where(EventGroup.name == data.name)
    )
    if existing is not None:
        raise ValueError("An event group with this name already exists")
    await _validate_event_group_roots(db, data.root_task_ids)

    group = EventGroup(
        name=data.name,
        schedule_recurrence=data.schedule_recurrence,
        schedule_weekdays=data.schedule_weekdays,
        schedule_hour=data.schedule_hour,
    )
    db.add(group)
    await db.flush()
    _add_event_group_members(db, group.id, data)
    await db.commit()
    return await get_event_group(db, group.id)


async def update_event_group(
    db: AsyncSession, group: EventGroup, data: EventGroupIn
) -> EventGroup:
    if data.name != group.name:
        existing = await db.scalar(
            select(EventGroup.id).where(
                EventGroup.name == data.name, EventGroup.id != group.id
            )
        )
        if existing is not None:
            raise ValueError("An event group with this name already exists")
    await _validate_event_group_roots(db, data.root_task_ids)

    group.name = data.name
    group.schedule_recurrence = data.schedule_recurrence
    group.schedule_weekdays = data.schedule_weekdays
    group.schedule_hour = data.schedule_hour
    # Wholesale replace — same "PATCH just resends the whole set"
    # semantics as Task.category_ids — simpler than diffing, and this
    # app's scale (a handful of roots/exclusions per group) makes the
    # delete-and-reinsert cost a non-issue.
    await db.execute(
        delete(EventGroupTask).where(EventGroupTask.event_group_id == group.id)
    )
    await db.execute(
        delete(EventGroupExclusion).where(
            EventGroupExclusion.event_group_id == group.id
        )
    )
    _add_event_group_members(db, group.id, data)
    await db.commit()
    return await get_event_group(db, group.id)


def _add_event_group_members(
    db: AsyncSession, group_id: int, data: EventGroupIn
) -> None:
    """Shared by create/update — must be called on a session with the
    group's own old membership rows already gone (update_event_group)
    or never having existed (create_event_group). Not itself async: it
    only calls db.add, which doesn't hit the database — the caller
    commits once after this returns."""
    root_ids = list(dict.fromkeys(data.root_task_ids))  # de-dupe, keep order
    # A root can't also be excluded — silently drop the overlap rather
    # than erroring, since the frontend never offers that combination
    # in the first place (a root is never shown as a descendant to
    # exclude from its own group).
    excluded_ids = set(data.excluded_task_ids) - set(root_ids)
    for position, task_id in enumerate(root_ids, start=1):
        db.add(
            EventGroupTask(event_group_id=group_id, task_id=task_id, position=position)
        )
    for task_id in excluded_ids:
        db.add(EventGroupExclusion(event_group_id=group_id, task_id=task_id))


async def delete_event_group(db: AsyncSession, group: EventGroup) -> None:
    await db.delete(group)
    await db.commit()


async def get_event_group_run(db: AsyncSession, run_id: int) -> EventGroupRun | None:
    return await db.get(EventGroupRun, run_id)


async def preview_event_group(
    db: AsyncSession, root_task_ids: list[int], excluded_task_ids: list[int]
) -> list[dict]:
    """Computes the full set of tasks an event group covers RIGHT NOW:
    every root, plus each root's current direct chain children — the
    one-level chain cap (see TaskChainLink) means that's the entire
    tree, no recursion needed. Deliberately stateless (task ids in, not
    a saved EventGroup) so the exact same computation serves the
    create-modal's live preview (before a group has ever been saved)
    and a fresh pre-trigger preview — a chain link added after the
    group was saved shows up automatically either way, since this never
    reads cached membership for which descendants exist, only for which
    ones are excluded."""
    excluded = set(excluded_task_ids)
    items: list[dict] = []
    for task_id in root_task_ids:
        task = await get_task(db, task_id)
        if task is None:
            continue
        items.append(
            {
                "task_id": task.id,
                "task_name": task.name,
                "points": task.points,
                "is_root": True,
                "parent_task_name": None,
                "excluded": False,
            }
        )
        links = await list_chain_links(db, task_id)
        for link in links:
            items.append(
                {
                    "task_id": link.child_task_id,
                    "task_name": link.child_task.name,
                    "points": link.child_task.points,
                    "is_root": False,
                    "parent_task_name": task.name,
                    "excluded": link.child_task_id in excluded,
                }
            )
    return items


async def trigger_event_group(
    db: AsyncSession, group: EventGroup, user: HouseholdUser | None
) -> tuple[EventGroupRun, list[TodoItem]]:
    """Creates one open TodoItem per root task, all tagged with a new
    EventGroupRun, fairly distributed across eligible users in one
    batch — the same fairness picture (`_gather_balancer_load`) and
    balancing logic (`balancing.balance`) the daily sweep uses, just run
    once immediately instead of waiting for it. Re-validates the roots
    (a task could have gone inactive or become someone's chain child
    since the group was saved) rather than trusting the saved
    membership blindly.

    `user` is None only for a scheduled auto-trigger
    (run_scheduled_event_groups_if_due) — there's no human actor for
    that, so `EventGroupRun.triggered_by_id`/`TodoItem.created_by_id`
    are both left null rather than attributed to whoever happens to be
    the admin running the server."""
    if not group.roots:
        raise ValueError("This event group has no tasks yet")
    await _validate_event_group_roots(db, [r.task_id for r in group.roots])

    run = EventGroupRun(
        event_group_id=group.id, triggered_by_id=user.id if user else None
    )
    db.add(run)
    await db.flush()

    # due_date stays UTC-anchored, same as every other due_date in this
    # service (see CLAUDE.md) — deliberately NOT the same value as the
    # fairness pass below, which needs the household's own local day so
    # it agrees with run_balancing's own week/month boundaries.
    today = datetime.now(UTC).date()
    created: list[TodoItem] = []
    for root in group.roots:
        todo = TodoItem(
            title=root.task.name,
            description=root.task.description,
            points=root.task.points,
            due_date=today,
            created_by_id=user.id if user else None,
            source_task_id=root.task_id,
            event_group_run_id=run.id,
            # A root's own chain children get spawned below, right in
            # this same trigger — never a second time at completion.
            chain_spawn_handled=True,
        )
        db.add(todo)
        created.append(todo)
    await db.flush()  # need ids for CandidateTodo below

    all_users = await list_household_users(db)
    eligible = [u for u in all_users if _is_eligible_for_tasks(u)]
    if eligible:
        settings = await get_settings_row(db)
        fairness_as_of = (
            datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
        )
        week_start, _week_end = _resolve_period(
            ReportPeriod.week, fairness_as_of, settings.week_start_weekday
        )
        (
            load_points,
            load_count,
            points_this_week,
            _current,
            _remaining,
        ) = await _gather_balancer_load(db, eligible, fairness_as_of, week_start)
        balancing_users = [
            balancing.EligibleUser(
                user_id=u.id,
                points_this_week=points_this_week[u.id],
                already_assigned_points=load_points[u.id],
                already_assigned_count=load_count[u.id],
            )
            for u in eligible
        ]
        # Must exceed everyone's current count plus this whole batch —
        # same reasoning as _assign_chain_todo_now's own cap: this call
        # hands out a fixed number of items in one go, not a capped
        # daily ration, so nobody should be skipped just for already
        # holding something.
        max_new_items_per_user = max(load_count.values(), default=0) + len(created)
        # `created` and `group.roots` were built in lockstep above (one
        # todo per root, same order) — zip pairs each todo back to the
        # root task it might be pinned through. A root's OWN pin, if
        # any — not to be confused with its chain children, which can
        # never themselves be pinned (see Task.pinned_user_id).
        result = balancing.balance(
            users=balancing_users,
            tasks=[],
            todos=[
                balancing.CandidateTodo(
                    todo_id=todo.id,
                    points=todo.points,
                    pinned_user_id=root.task.pinned_user_id,
                )
                for todo, root in zip(created, group.roots)
            ],
            max_new_items_per_user=max_new_items_per_user,
        )
        for todo in created:
            picked = result.todo_assignments.get(todo.id)
            if picked is not None:
                todo.assigned_to_id = picked

    # Each root's own chain children spawn now too, not just at its
    # eventual completion — same request as the New Todo / "From task"
    # path (crud.create_todo). Must happen AFTER the batch balance pass
    # above, since a same_user child's/different_user exclusion's
    # anchor is the root's FINAL assigned_to_id, not an intermediate
    # unassigned state. `root_todo` (not the fresh refetch below) is
    # kept around per child so each notification can name its own root.
    spawned: list[tuple[TodoItem, list[TodoItem]]] = []
    for root_todo in created:
        children = await _spawn_chain_children_on_creation(
            db, parent_todo=root_todo, event_group_run_id=run.id
        )
        spawned.append((root_todo, children))

    await db.commit()

    root_ids = {t.id for t in created}
    all_ids = list(root_ids) + [c.id for _root, children in spawned for c in children]
    result = await db.execute(
        _todo_query().where(TodoItem.id.in_(all_ids)).order_by(TodoItem.id)
    )
    fresh_todos = list(result.scalars().all())
    for todo in fresh_todos:
        if todo.id not in root_ids or todo.assigned_to_id is None:
            continue
        if user is not None:
            await notify_todo_assigned(db, todo, user)
        else:
            # notify_todo_assigned's "X asked you to" wording needs a
            # requester — a scheduled trigger has none, so this gets its
            # own body naming the group instead. todo.assigned_to is
            # already eager-loaded via _todo_query() (fresh_todos came
            # from there), so no extra fetch for the language either.
            lang = todo.assigned_to.preferred_language
            await _notify(
                db,
                todo.assigned_to_id,
                title=t(lang, "scheduled_task.title"),
                body=t(lang, "scheduled_task.body", group=group.name, todo=todo.title),
                url="/board",
            )
    for root_todo, children in spawned:
        for child in children:
            if child.assigned_to_id is not None:
                await notify_chain_child_spawned(db, child, root_todo.title)
    return run, fresh_todos


def _event_group_due(
    recurrence: str | None,
    weekdays: list[int] | None,
    hour: int,
    ran_today: bool,
    now: datetime,
    *,
    tz: str = "UTC",
) -> bool:
    """Pure predicate behind run_scheduled_event_groups_if_due, kept
    separate so it's unit-testable without waiting for a real clock
    hour to roll around. An exact hour match, not `>=` — same reasoning
    as run_scheduled_nudge_if_due: `>=` would fire immediately the
    moment someone saves a schedule whose hour already passed today,
    and would fire a whole backlog of missed hours after downtime
    instead of just the one tick that's actually due.

    `now` is the real instant (any aware datetime — UTC in practice);
    `tz` is HouseholdSettings.timezone, and the hour/weekday check is
    done against `now` converted INTO that zone, not raw UTC — an
    admin picking "18" means 18:00 in their own timezone, not UTC,
    which this used to assume (user report: "Time for time scheduled
    event groups is in UTC"). Defaults to "UTC" so every existing call
    site/test that doesn't pass `tz` keeps its old, exact behavior.

    DST caveat, not handled specially: on a spring-forward day, a
    schedule set for the hour that gets skipped (e.g. 02:00 in a zone
    that jumps 02:00->03:00) simply never matches that day — there's
    no "02:00" to compare against. On a fall-back day, the repeated
    hour matches on its first occurrence; `ran_today` then suppresses
    the second."""
    if recurrence is None or ran_today:
        return False
    local_now = now.astimezone(ZoneInfo(tz))
    if local_now.hour != hour:
        return False
    if recurrence == "daily":
        return True
    if recurrence == "weekly":
        return bool(weekdays) and local_now.weekday() in weekdays
    return False


async def run_scheduled_event_groups_if_due(
    db: AsyncSession, *, now: datetime | None = None
) -> list[tuple[EventGroup, EventGroupRun, list[TodoItem]]]:
    """Called hourly by household_service.scheduler. Checks every
    scheduled group independently (`now` injectable so a live tick can
    be run on demand — in tests, or to verify this without waiting for
    the clock to actually reach the right hour). "Already ran today"
    counts a MANUAL trigger too, not just a previous scheduled one —
    triggering "Dinner" by hand earlier the same day should suppress
    tonight's automatic one, not produce a second Dinner. "Today" here
    means the household's configured local calendar day (Household
    Settings.timezone), not UTC's — `since`/`until` are that local
    day's own midnight-to-midnight span, converted to UTC for the
    query, which stays correct across a DST shift (that day is 23 or
    25 hours long in UTC terms, and this captures exactly that span,
    not a flat 24h window).

    One group's failure (e.g. a root went inactive since the group was
    saved — trigger_event_group raises ValueError) is caught and logged
    rather than aborting every other group's check in the same tick;
    the rollback matters because a failed flush/commit leaves the
    session unusable for whatever runs next in the same tick otherwise."""
    now = now or datetime.now(UTC)
    settings = await get_settings_row(db)
    tz = ZoneInfo(settings.timezone)
    local_today = now.astimezone(tz).date()
    since = datetime.combine(local_today, time.min, tzinfo=tz).astimezone(UTC)
    until = datetime.combine(local_today, time.max, tzinfo=tz).astimezone(UTC)

    result = await db.execute(
        select(EventGroup)
        .where(EventGroup.schedule_recurrence.is_not(None))
        .options(selectinload(EventGroup.roots).selectinload(EventGroupTask.task))
    )
    groups = list(result.scalars().all())

    triggered: list[tuple[EventGroup, EventGroupRun, list[TodoItem]]] = []
    for group in groups:
        ran_today = await db.scalar(
            select(EventGroupRun.id).where(
                EventGroupRun.event_group_id == group.id,
                EventGroupRun.triggered_at >= since,
                EventGroupRun.triggered_at <= until,
            )
        )
        if not _event_group_due(
            group.schedule_recurrence,
            group.schedule_weekdays,
            group.schedule_hour,
            ran_today is not None,
            now,
            tz=settings.timezone,
        ):
            continue
        try:
            run, todos = await trigger_event_group(db, group, None)
        except ValueError:
            logger.warning(
                "Scheduled trigger of event group %s (%r) failed",
                group.id,
                group.name,
                exc_info=True,
            )
            await db.rollback()
            continue
        triggered.append((group, run, todos))
    return triggered


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
    db: AsyncSession,
    task: Task,
    user: HouseholdUser,
    *,
    force: bool = False,
    force_daily_cap: bool = False,
) -> PointsEntry:
    """Logs one completion of `task` by `user` and awards points, including
    the configured ramp-up bonus if this user is (so far) the only one who
    has ever completed this task. Rejects a completion past the task's own
    `times_per_day` for today (by anyone, not just this user) — without
    this, a 1x/day task never actually went away, and repeated taps just
    kept awarding points indefinitely. `force_daily_cap=True` overrides
    ONLY this check — the frontend shows how many times it's already been
    logged today and confirms explicitly before setting this, same
    "informed override, not a silent bypass" contract `force` below
    already uses for the chain-child check; kept as its own independent
    flag rather than folded into `force` so a chain-child override can
    never silently also bypass the daily cap, or vice versa.

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
    second-guess.

    A `Recurrence.manual` task has no automatic occurrence of its own —
    it's normally only ever instantiated as a todo (an Event Group root,
    a chain spawn, or a Board "From task" post), completed there via
    `complete_todo` instead. This function nonetheless allows completing
    one directly too (user request: a manual task that was never wired
    into an Event Group or chain would otherwise have no way to ever be
    completed at all, and manual is now the default recurrence for a
    newly created task — see TaskCreate's own default). Goes through the
    exact same path as any other recurrence from here on (times_per_day,
    ramp-up, chain-spawning its own children if it happens to be a chain
    PARENT) — being a chain CHILD is still blocked by the check above,
    `force` still required for that, same as ever; this only removed the
    recurrence-based rejection, not the chain-child one."""
    if await is_chain_child(db, task.id) and not force:
        raise ValueError(
            f'"{task.name}" is a chained task — complete it from the todo '
            "it's spawned as, not directly"
        )
    done_today = await _completions_today_count(db, task.id)
    if done_today >= task.times_per_day and not force_daily_cap:
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
        selectinload(TodoItem.event_group_run).selectinload(EventGroupRun.event_group),
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
    if (
        data.source_task_id is not None
        and await get_task(db, data.source_task_id) is None
    ):
        raise ValueError(f"Unknown task id: {data.source_task_id}")
    todo = TodoItem(
        title=data.title,
        description=data.description,
        points=data.points,
        due_date=_todo_due_date(data.due_in_days),
        assigned_to_id=data.assigned_to_id,
        created_by_id=creator.id,
        source_task_id=data.source_task_id,
    )
    db.add(todo)
    await db.flush()  # need todo.id before spawning its own chain children
    to_notify: list[TodoItem] = []
    if data.source_task_id is not None:
        # "Handled" either way — actually spawned, or the creator
        # explicitly opted out — so complete_todo never spawns a second
        # set later (see that function's own guard).
        todo.chain_spawn_handled = True
        if data.spawn_chain_children:
            to_notify = await _spawn_chain_children_on_creation(db, parent_todo=todo)
    await db.commit()
    await db.refresh(
        todo,
        attribute_names=["created_by", "assigned_to", "completed_by", "created_at"],
    )
    for child in to_notify:
        await notify_chain_child_spawned(db, child, todo.title)
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
    """Completes `todo` and awards its points. Which Task (if any) this
    todo is an instance of — `chain_link.child_task_id` if it's a
    chain-spawned instance, else `source_task_id` if it was created
    directly from a task's own definition (an event group's root todos,
    "From task" on the New Todo form) — gets stamped onto the
    PointsEntry too, so `times_per_day`/assignment-progress counting
    sees this completion the same as a direct Task completion would.
    An ordinary, freely-typed todo has neither set, so this is a no-op
    for it, same as before.

    Chain children are normally spawned already, at the PARENT's own
    creation (crud._spawn_chain_children_on_creation via create_todo /
    trigger_event_group) — `todo.chain_spawn_handled` is true for any
    todo that went through that, whether it actually spawned anything
    or the creator explicitly opted out, so this never spawns a second
    set for one of those. Only still spawns here as a fallback for a
    todo that predates that change (chain_spawn_handled still false —
    old data) or one completed via a chain-child todo itself
    (`chain_link_id` set — always a no-op in practice, since chaining
    is capped at one level: a chain child can never itself be a
    parent)."""
    todo.status = TodoStatus.completed
    todo.completed_by_id = user.id
    todo.completed_at = datetime.now(UTC)
    represented_task_id: int | None = None
    if todo.chain_link_id is not None:
        link = await db.get(TaskChainLink, todo.chain_link_id)
        if link is not None:
            represented_task_id = link.child_task_id
    else:
        represented_task_id = todo.source_task_id
    entry = PointsEntry(
        household_user_id=user.id,
        points=todo.points,
        source=PointsSource.todo,
        todo_item_id=todo.id,
        task_id=represented_task_id,
    )
    db.add(entry)
    await db.flush()
    await _cancel_pending_takeover_for_todo(db, todo.id)
    to_notify: list[TodoItem] = []
    if represented_task_id is not None and not todo.chain_spawn_handled:
        to_notify = await _spawn_chain_children(
            db,
            parent_task_id=represented_task_id,
            entry=entry,
            completer=user,
            event_group_run_id=todo.event_group_run_id,
        )
    await db.commit()
    await db.refresh(todo, attribute_names=["completed_by", "completed_at", "status"])
    for child in to_notify:
        await notify_todo_assigned(db, child, user)
    return todo


async def cancel_todo(db: AsyncSession, todo: TodoItem) -> TodoItem:
    """Cancelling deletes any chain children this todo pre-spawned at
    its OWN creation that are still open (user request: "if the parent
    task gets cancelled the chain task gets deleted with it") — a
    pre-spawned child only exists as a forecast of the parent actually
    happening, and cancelling says it won't. Deliberately only the
    still-open ones: a child someone's already completed keeps standing
    on its own (they did real work; cancelling the parent afterward
    shouldn't claw that back), and one already cancelled on its own is
    left as-is too. The frontend warns about this before calling here
    (see GET /todos/{id}/chain-children / crud.list_chain_children) —
    this function itself just does it, unconditionally, once asked."""
    todo.status = TodoStatus.cancelled
    todo.cancelled_at = datetime.now(UTC)
    await _cancel_pending_takeover_for_todo(db, todo.id)
    await db.execute(
        delete(TodoItem).where(
            TodoItem.spawned_by_todo_id == todo.id, TodoItem.status == TodoStatus.open
        )
    )
    await db.commit()
    await db.refresh(todo, attribute_names=["status"])
    return todo


async def _hard_delete_todos(db: AsyncSession, todo_ids: list[int]) -> None:
    """Shared by every real (hard) delete path: a single todo
    (delete_todo), a whole event group run's worth at once
    (delete_event_group_run_todos), and the scheduled overdue cleanup
    (run_scheduled_overdue_cleanup). Does NOT commit — callers do, once,
    after whatever else they need in the same transaction.

    `TodoItem.spawned_by_todo_id`'s `ON DELETE CASCADE` doesn't look at
    status, so deleting an open parent would otherwise also wipe out a
    child that's already completed (and earned real points) or already
    cancelled on its own — unlike the softer crud.cancel_todo, which
    only ever removes a still-OPEN child. First detaches (nulls
    spawned_by_todo_id on) any non-open child of `todo_ids`, exactly the
    same "stays, just loses the why pointer" treatment chain_link_id's
    own ON DELETE SET NULL already gets elsewhere — then deletes. A
    child that's itself in `todo_ids` is unaffected by the detach (it's
    getting deleted outright anyway)."""
    if not todo_ids:
        return
    await db.execute(
        update(TodoItem)
        .where(
            TodoItem.spawned_by_todo_id.in_(todo_ids),
            TodoItem.status != TodoStatus.open,
        )
        .values(spawned_by_todo_id=None)
    )
    await db.execute(delete(TodoItem).where(TodoItem.id.in_(todo_ids)))


async def delete_todo(db: AsyncSession, todo: TodoItem) -> None:
    await _hard_delete_todos(db, [todo.id])
    await db.commit()


async def _event_group_run_cleanup_candidates(
    db: AsyncSession, run_id: int
) -> list[TodoItem]:
    """Every todo a bulk delete of this run would consider: todos
    actually tagged with the run (roots, plus any chain descendant that
    inherited the tag), PLUS any chain descendant spawned by one of
    those that ISN'T tagged — a descendant the group's creator
    explicitly excluded from the group's tag (EventGroupExclusion) is
    still part of "this event" for a bulk delete's purposes, it just
    never showed up clustered or badged for it. One level of lookup is
    enough: chaining is capped at one level, so a spawned child can
    never itself be a parent with further children."""
    tagged = await db.execute(
        select(TodoItem).where(TodoItem.event_group_run_id == run_id)
    )
    tagged_todos = list(tagged.scalars().all())
    tagged_ids = {t.id for t in tagged_todos}
    if not tagged_ids:
        return []
    spawned = await db.execute(
        select(TodoItem).where(TodoItem.spawned_by_todo_id.in_(tagged_ids))
    )
    extra = [t for t in spawned.scalars().all() if t.id not in tagged_ids]
    return tagged_todos + extra


async def event_group_run_delete_preview(
    db: AsyncSession, run_id: int
) -> tuple[list[TodoItem], list[TodoItem]]:
    """What a bulk delete of this run would do, without doing it —
    backs the frontend's confirmation warning. Returns (to_delete,
    to_keep): to_keep is whichever of the candidates is already
    completed (kept untouched — they earned real points), to_delete is
    everything else (open or already-cancelled)."""
    candidates = await _event_group_run_cleanup_candidates(db, run_id)
    to_keep = [t for t in candidates if t.status == TodoStatus.completed]
    to_delete = [t for t in candidates if t.status != TodoStatus.completed]
    return to_delete, to_keep


async def delete_event_group_run_todos(
    db: AsyncSession, run_id: int
) -> tuple[list[TodoItem], list[TodoItem]]:
    """Actually performs the bulk delete the preview above describes —
    same candidate computation, so the two can never disagree about
    what's affected. Routes through _hard_delete_todos so a completed
    todo among the candidates is detached and spared, not swept away by
    spawned_by_todo_id's cascade, even though it's also one of the
    things event_group_run_delete_preview would have called a
    'candidate'."""
    to_delete, to_keep = await event_group_run_delete_preview(db, run_id)
    await _hard_delete_todos(db, [t.id for t in to_delete])
    await db.commit()
    return to_delete, to_keep


async def run_scheduled_overdue_cleanup(
    db: AsyncSession, *, today: date | None = None
) -> list[TodoItem]:
    """Called hourly by household_service.scheduler (no "already ran
    today" dedup needed, unlike the nudge/balancing/event-group ticks —
    the query is naturally idempotent: once a row's gone, it can't
    match again). `today` is injectable so this can be exercised
    without waiting for the clock, same reasoning as
    crud._event_group_due's own `now` parameter.

    One setting, three independent conditions it sweeps for, matching
    the admin panel's single "auto remove after" field:
    1. still-OPEN, overdue by more than N days — the original behavior.
       "Overdue" means the same thing the Board's own due-date badge
       does (util.js's dueBadge: due_date < today, both anchored to
       UTC); this just adds N days of grace before deleting it, not
       the day it first turns overdue.
    2. COMPLETED more than N days ago (completed_at).
    3. CANCELLED more than N days ago (cancelled_at) — NULL for
       anything cancelled before that column existed (see
       TodoItem.cancelled_at's own docstring); this comparison
       naturally excludes those rather than guessing an age for them,
       so they're simply never swept, not retroactively cleaned up.
    All three compare against the same day-level cutoff (not a live
    timestamp) for consistency with the open/due_date case above —
    this runs hourly, so day-level granularity is all "after N days"
    needs in practice."""
    settings = await get_settings_row(db)
    if settings.overdue_delete_after_days is None:
        return []
    today = today or datetime.now(UTC).date()
    cutoff_date = today - timedelta(days=settings.overdue_delete_after_days)
    cutoff_dt = datetime.combine(cutoff_date, time.min, tzinfo=UTC)
    result = await db.execute(
        select(TodoItem).where(
            or_(
                and_(
                    TodoItem.status == TodoStatus.open,
                    TodoItem.due_date.is_not(None),
                    TodoItem.due_date < cutoff_date,
                ),
                and_(
                    TodoItem.status == TodoStatus.completed,
                    TodoItem.completed_at.is_not(None),
                    TodoItem.completed_at < cutoff_dt,
                ),
                and_(
                    TodoItem.status == TodoStatus.cancelled,
                    TodoItem.cancelled_at.is_not(None),
                    TodoItem.cancelled_at < cutoff_dt,
                ),
            )
        )
    )
    stale = list(result.scalars().all())
    if stale:
        await _hard_delete_todos(db, [t.id for t in stale])
        await db.commit()
    return stale


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
    if as_of is None:
        settings = await get_settings_row(db)
        as_of = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
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
    db: AsyncSession, todo: TodoItem, *, exclude_user_id: int | None
) -> None:
    """Immediately assigns a freshly-spawned "different person" chain
    child to whoever's currently least loaded, using the exact same
    fairness picture run_balancing's sweep uses — just invoked for this
    one todo right now instead of waiting for the next scheduled run (a
    once-a-day cadence would otherwise leave a same-day chain todo
    unassigned for hours). Never assigns to `exclude_user_id` (whoever
    completed the parent at completion-time spawn, or whoever the
    parent todo is currently assigned to at creation-time spawn — see
    _spawn_chain_children / _spawn_chain_children_on_creation — None if
    there's nobody to exclude, e.g. the parent is itself unassigned).
    Left open/unassigned if nobody else is eligible — exactly like an
    ordinary sweep leftover, and still excluded from self-claiming (see
    claim_todo)."""
    settings = await get_settings_row(db)
    as_of = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
    all_users = await list_household_users(db)
    eligible = [u for u in all_users if _is_eligible_for_tasks(u)]
    if not eligible:
        return

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


async def _event_group_exclusions(db: AsyncSession, event_group_id: int) -> set[int]:
    result = await db.execute(
        select(EventGroupExclusion.task_id).where(
            EventGroupExclusion.event_group_id == event_group_id
        )
    )
    return {row[0] for row in result.all()}


async def _excluded_task_ids_for_run(
    db: AsyncSession, event_group_run_id: int | None
) -> set[int]:
    if event_group_run_id is None:
        return set()
    run = await db.get(EventGroupRun, event_group_run_id)
    if run is None:
        return set()
    return await _event_group_exclusions(db, run.event_group_id)


async def _spawn_one_chain_child(
    db: AsyncSession,
    link: TaskChainLink,
    *,
    due_date: date,
    created_by_id: int | None,
    anchor_user_id: int | None,
    spawned_by_entry_id: int | None,
    spawned_by_todo_id: int | None,
    event_group_run_id: int | None,
    excluded_task_ids: set[int],
) -> TodoItem | None:
    """Builds and persists one chain-spawned TodoItem for `link` — the
    shared tail of both _spawn_chain_children (completion-time) and
    _spawn_chain_children_on_creation (creation-time), which only
    differ in WHEN they run and what `anchor_user_id` means (whoever
    completed the parent, vs. whoever the parent is currently assigned
    to). `anchor_user_id` is who a same_user link assigns directly to,
    or who a different_user link's balancer pick excludes — either can
    be None (same_user: parent unassigned, so leave the child
    unassigned too; different_user: nobody to exclude).

    Returns the child whenever it ended up with a real assignee (either
    branch), so a caller that wants to notify someone can — the two
    callers differ on whether a same_user pick is worth notifying (see
    each one's own docstring for why), so that filtering happens on
    their side, not here."""
    child = TodoItem(
        title=link.child_task.name,
        description=link.child_task.description,
        points=link.child_task.points,
        due_date=due_date,
        created_by_id=created_by_id,
        chain_link_id=link.id,
        spawned_by_entry_id=spawned_by_entry_id,
        spawned_by_todo_id=spawned_by_todo_id,
    )
    if event_group_run_id is not None and link.child_task_id not in excluded_task_ids:
        child.event_group_run_id = event_group_run_id
    if link.same_user:
        # Direct assignment, bypassing the balancer entirely — this is
        # "the same person does both," not a fairness decision.
        child.assigned_to_id = anchor_user_id
        db.add(child)
        await db.flush()
        return child if child.assigned_to_id is not None else None
    child.exclude_user_id = anchor_user_id
    db.add(child)
    await db.flush()
    await _assign_chain_todo_now(db, child, exclude_user_id=anchor_user_id)
    return child if child.assigned_to_id is not None else None


async def _spawn_chain_children(
    db: AsyncSession,
    *,
    parent_task_id: int,
    entry: PointsEntry,
    completer: HouseholdUser,
    event_group_run_id: int | None = None,
) -> list[TodoItem]:
    """Spawns one TodoItem per chain link hanging off `parent_task_id`,
    for the occurrence just logged as `entry`. Must run in the same
    transaction as `entry`'s own flush (the caller flushes first so
    entry.id exists, then commits once after this returns) — a crash
    between the two can never leave points awarded with no matching
    children, or vice versa. Idempotent via uq_todo_chain_spawn
    (chain_link_id, spawned_by_entry_id) if this is ever retried for the
    same entry.

    Still the only path for a Task completed directly (crud.
    complete_task — a daily standing chore, or a weekly/monthly one
    completed straight from Home, neither of which is ever a TodoItem),
    and the fallback for a todo that predates _spawn_chain_children_on_
    creation (chain_spawn_handled still false — see complete_todo).

    `event_group_run_id`: if the completed todo that triggered this was
    itself tagged with an event group run, each spawned child inherits
    the same tag — UNLESS that specific child task is one the group's
    creator explicitly excluded from grouping (EventGroupExclusion; see
    PROJECT_SPEC.md's "Event groups") — so a "Dinner" run's chain
    reactions stay clustered with it on the Board, except the ones
    someone deliberately said don't count as a Dinner task.

    Returns the different-person children that got assigned, for the
    caller to push-notify AFTER its own final commit —
    push.send_to_subscriptions commits internally (it prunes dead
    subscriptions as it goes), so notifying from inside this function,
    before the caller's commit, would split one logical transaction
    (points entry + all spawned children) into several."""
    links = await list_chain_links(db, parent_task_id)
    if not links:
        return []

    excluded_task_ids = await _excluded_task_ids_for_run(db, event_group_run_id)
    to_notify: list[TodoItem] = []
    for link in links:
        child = await _spawn_one_chain_child(
            db,
            link,
            due_date=datetime.now(UTC).date(),
            created_by_id=completer.id,
            anchor_user_id=completer.id,
            spawned_by_entry_id=entry.id,
            spawned_by_todo_id=None,
            event_group_run_id=event_group_run_id,
            excluded_task_ids=excluded_task_ids,
        )
        # A same_user child is assigned straight to `completer` — the
        # very person who just completed the parent — so notifying
        # them about a task they implicitly just gave themselves would
        # be pointless. Only a different_user pick is worth telling
        # someone about here.
        if child is not None and not link.same_user:
            to_notify.append(child)
    return to_notify


async def _spawn_chain_children_on_creation(
    db: AsyncSession,
    *,
    parent_todo: TodoItem,
    event_group_run_id: int | None = None,
) -> list[TodoItem]:
    """The creation-time sibling of _spawn_chain_children — called right
    when `parent_todo` itself is created (crud.create_todo /
    trigger_event_group), not when it's completed, per the user's
    explicit request: chain tasks should already exist alongside their
    parent, not only appear once the parent's actually done.

    `parent_todo` must already have an id (caller flushes first) and
    its final `assigned_to_id` already decided — for an event group's
    root this means AFTER the batch balancer pass has assigned it, not
    before, since that's what `anchor_user_id` resolves to here.
    Idempotent via uq_todo_chain_spawn_by_todo (chain_link_id,
    spawned_by_todo_id).

    Deliberately does NOT try to keep a same_user child in sync with
    the parent's assignee afterward — reassigning, claiming, or taking
    over the parent later never touches an already-spawned child (user
    request: "reassignment only changes the reassigned task without
    touching the chain task"). If the parent is unassigned right now,
    a same_user child is created unassigned too, and a different_user
    child's balancer pick has nobody in particular to exclude."""
    links = await list_chain_links(db, parent_todo.source_task_id)
    if not links:
        return []

    excluded_task_ids = await _excluded_task_ids_for_run(db, event_group_run_id)
    to_notify: list[TodoItem] = []
    for link in links:
        child = await _spawn_one_chain_child(
            db,
            link,
            due_date=parent_todo.due_date or datetime.now(UTC).date(),
            created_by_id=parent_todo.created_by_id,
            anchor_user_id=parent_todo.assigned_to_id,
            spawned_by_entry_id=None,
            spawned_by_todo_id=parent_todo.id,
            event_group_run_id=event_group_run_id,
            excluded_task_ids=excluded_task_ids,
        )
        # Unlike _spawn_chain_children's completion-time notify filter,
        # a same_user pick here is still worth telling someone about —
        # the anchor is whoever the PARENT happens to be assigned to,
        # not whoever's currently acting, so it's very possibly someone
        # who hasn't touched this page at all yet.
        if child is not None:
            to_notify.append(child)
    return to_notify


async def notify_chain_child_spawned(
    db: AsyncSession, child: TodoItem, parent_title: str
) -> None:
    """Notifies whoever a chain-spawned child landed on at CREATION
    time (_spawn_chain_children_on_creation) — distinct wording from
    notify_todo_assigned's "X asked you to," since nobody asked for
    this, it's an automatic side effect of the parent now existing."""
    lang = await _recipient_language(db, child.assigned_to_id)
    await _notify(
        db,
        child.assigned_to_id,
        title=t(lang, "chain_task.title"),
        body=t(lang, "chain_task.body", parent=parent_title, child=child.title),
        url="/board",
    )


async def list_chain_children(db: AsyncSession, todo_id: int) -> list[TodoItem]:
    """Still-open children pre-spawned at `todo_id`'s own creation — the
    ones crud.cancel_todo would delete if this todo got cancelled right
    now. Used only to warn about that before it happens (GET /todos/
    {id}/chain-children); see cancel_todo for why only OPEN ones."""
    result = await db.execute(
        select(TodoItem).where(
            TodoItem.spawned_by_todo_id == todo_id, TodoItem.status == TodoStatus.open
        )
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
    settings = await get_settings_row(db)
    as_of = as_of or datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
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

    # Collects moves from BOTH pin correction (below) and the rebalance
    # pass (further down) — same (row, from_uid, to_uid, points) shape,
    # so the one block that applies tallies/push summaries/pending-
    # takeover-request cancellation further down handles either kind
    # identically; a pin correction cancelling a stale pending request
    # on the assignment it just moved is exactly as correct as
    # rebalance's own pull doing the same.
    reassignments: list[tuple[TaskAssignment, int, int, int]] = []
    now = datetime.now(UTC)

    # ---- pin correction: tasks with an "always assign to" owner --------
    # Moves an EXISTING assignment back to its pinned owner when it's
    # currently held by someone else — e.g. the pin was just set, or
    # changed, after this period's assignment was already made. Runs
    # before the sweep so a freshly-corrected pin's load is reflected
    # before anything else is decided this run. Not itself a fairness
    # computation (see balancing.correct_pins's own docstring) — a
    # pinned task that's ALREADY correctly held, or has no pin at all,
    # never shows up here.
    pinned_candidates = [
        balancing.PinnedAssignment(
            assignment_id=a.id,
            holder_id=a.household_user_id,
            pinned_user_id=a.task.pinned_user_id,
            remaining_points=remaining_by_assignment[a.id],
            has_progress=(
                await _completed_instance_count(
                    db, a.task_id, a.period_start, a.period_end
                )
                > 0
            ),
            already_reassigned=a.reassigned_at is not None,
        )
        for a in current_assignments
        if a.task.pinned_user_id is not None
        and a.task.pinned_user_id != a.household_user_id
    ]
    pin_moves = balancing.correct_pins(
        assignments=pinned_candidates, eligible_user_ids=set(eligible_by_id)
    )
    for assignment_id, from_uid, to_uid in pin_moves:
        row = assignment_by_id[assignment_id]
        pts = remaining_by_assignment[assignment_id]
        row.household_user_id = to_uid
        row.reassigned_at = now
        reassignments.append((row, from_uid, to_uid, pts))
        if from_uid in load_points:
            load_points[from_uid] -= pts
            load_count[from_uid] -= 1
        load_points[to_uid] += pts
        load_count[to_uid] += 1

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
        select(Task).where(
            Task.active.is_(True),
            # Explicit allow-list, not `!= daily` — a `manual` task
            # (Recurrence.manual) must never reach the sweep either;
            # `!= daily` alone would let it through, and `_task_period`'s
            # own weekly-or-else-monthly logic would then wrongly treat
            # it as monthly and hand it a real TaskAssignment every
            # month, exactly the "automatically created" behavior
            # Recurrence.manual exists to NOT have.
            Task.recurrence.in_([Recurrence.weekly, Recurrence.monthly]),
        )
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
        # A pinned task never reaches balance()'s ramp-up-stickiness/
        # rotation branch at all (see balancing.balance's pinned
        # bypass) — skip the otherwise-wasted assignment-history query
        # for it.
        history = []
        if task.pinned_user_id is None:
            history_result = await db.execute(
                select(TaskAssignment.household_user_id)
                .where(
                    TaskAssignment.task_id == task.id,
                    TaskAssignment.period_start < p_start,
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
                pinned_user_id=task.pinned_user_id,
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
    # An unclaimed todo has no pin of its own — only the Task it was
    # posted from might (picked via the "From task" selector on the
    # New Todo form, or an event group root re-triggered another way).
    # A separate, targeted lookup rather than reusing task_by_id above,
    # since that dict only has ACTIVE non-daily tasks — a todo can
    # reference a task that's since gone inactive or daily, and this
    # only needs the one column, not the whole row.
    source_task_ids = {
        t.source_task_id for t in unclaimed_todos.values() if t.source_task_id
    }
    pinned_by_source_task: dict[int, int] = {}
    if source_task_ids:
        pin_rows = await db.execute(
            select(Task.id, Task.pinned_user_id).where(
                Task.id.in_(source_task_ids), Task.pinned_user_id.isnot(None)
            )
        )
        pinned_by_source_task = dict(pin_rows.all())
    candidate_todos = [
        balancing.CandidateTodo(
            todo_id=t.id,
            points=t.points,
            excluded_user_id=t.exclude_user_id,
            pinned_user_id=(
                pinned_by_source_task.get(t.source_task_id)
                if t.source_task_id
                else None
            ),
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
                # Whether it's correctly held or just got moved there by
                # the pin-correction pass above, a pinned task is never
                # a fairness pull target — see balancing.rebalance's own
                # `not a.pinned` gate.
                pinned=a.task.pinned_user_id is not None,
            )
        )

    moves = balancing.rebalance(
        users=_balancing_users(),
        assignments=pullable,
        weekly_points_goal=settings.weekly_points_goal,
        max_new_items_per_user=max_new_items_per_user,
    )

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
    trigger got there first) every later tick this same day is a no-op.
    "Today" is the household's own configured local calendar day
    (HouseholdSettings.timezone), not UTC's — otherwise this fires near
    UTC midnight regardless of the household's timezone, which can land
    in the middle of someone's actual day far from UTC and makes the
    daily sweep/rebalance less likely to have already run by the time a
    returning-from-break user becomes eligible again (see
    _release_user_assignments)."""
    settings = await get_settings_row(db)
    today = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
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
    """Notifies the target when someone asks them to take something
    over — in-app always, push best-effort (see _notify). Called by the
    route AFTER create_takeover_request_for_* already committed —
    _notify commits internally too, so calling it mid-transaction would
    split one logical write into several (see _spawn_chain_children's
    own note)."""
    lang = await _recipient_language(db, req.target_id)
    await _notify(
        db,
        req.target_id,
        title=t(lang, "takeover_requested.title"),
        body=t(
            lang,
            "takeover_requested.body",
            requester=req.requester.display_name,
            item=_takeover_item_label(req),
        ),
        url="/home",
    )


async def notify_takeover_responded(db: AsyncSession, req: TakeoverRequest) -> None:
    """Notifies the requester once the target answers. Same after-commit
    timing as notify_takeover_requested."""
    lang = await _recipient_language(db, req.requester_id)
    verb_key = (
        "verb.accepted" if req.status == TakeoverStatus.accepted else "verb.declined"
    )
    verb = t(lang, verb_key)
    await _notify(
        db,
        req.requester_id,
        title=t(lang, "takeover_responded.title", verb=verb),
        body=t(
            lang,
            "takeover_responded.body",
            target=req.target.display_name,
            verb=verb,
            item=_takeover_item_label(req),
        ),
        url="/home",
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
    settings.overdue_delete_after_days = data.overdue_delete_after_days
    settings.timezone = data.timezone
    settings.default_language = data.default_language
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


# ---- Notification inbox --------------------------------------------------


async def _recipient_language(db: AsyncSession, household_user_id: int) -> str:
    """A notification's title/body is rendered in ITS RECIPIENT's own
    language, not the sender's or the household's — an extra by-
    primary-key fetch (cheap, and this is a low-frequency path, not a
    hot one) rather than trusting that whatever relationship happened
    to already be loaded on some caller's object graph includes this
    particular field. "en" if the user's somehow gone (shouldn't
    happen — notifying a deleted user isn't a real case) rather than
    raising on something this unrelated to the actual notification."""
    recipient = await get_household_user(db, household_user_id)
    return recipient.preferred_language if recipient else "en"


async def _notify(
    db: AsyncSession, household_user_id: int, *, title: str, body: str, url: str
) -> int:
    """The one place that creates a notification — both the durable
    in-app record (`Notification`, what the bell/inbox actually reads)
    and a best-effort push. Always creates the in-app record, even with
    no push subscription — a push-only call site is exactly what let an
    admin reassign go completely unnoticed by a user without push
    enabled (no subscription, denied the permission prompt, or just a
    browser that doesn't support it). Returns how many of the push
    sends actually succeeded (0 if there's no subscription, or delivery
    failed for all of them) — callers that track push-delivery stats
    specifically (send_weekly_nudge) use this instead of duplicating
    the subscription lookup themselves."""
    db.add(
        Notification(
            household_user_id=household_user_id, title=title, body=body, url=url
        )
    )
    await db.commit()
    subs = await get_subscriptions_for_user(db, household_user_id)
    if not subs:
        return 0
    return await push.send_to_subscriptions(
        db, subs, {"title": title, "body": body, "url": url}
    )


async def get_notification(
    db: AsyncSession, notification_id: int
) -> Notification | None:
    return await db.get(Notification, notification_id)


async def list_notifications(
    db: AsyncSession,
    household_user_id: int,
    *,
    unread_only: bool = False,
    limit: int = 30,
) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.household_user_id == household_user_id
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_notification_read(
    db: AsyncSession, notification: Notification
) -> Notification:
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(notification)
    return notification


async def mark_all_notifications_read(db: AsyncSession, household_user_id: int) -> int:
    result = await db.execute(
        update(Notification)
        .where(
            Notification.household_user_id == household_user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount


async def notify_todo_assigned(
    db: AsyncSession, todo: TodoItem, requested_by: HouseholdUser
) -> None:
    """Notifies whoever a new todo was requested from — in-app always,
    push best-effort (see _notify)."""
    if todo.assigned_to_id is None:
        return
    lang = await _recipient_language(db, todo.assigned_to_id)
    await _notify(
        db,
        todo.assigned_to_id,
        title=t(lang, "chore_request.title"),
        body=t(
            lang,
            "chore_request.body",
            requester=requested_by.display_name,
            todo=todo.title,
        ),
        url="/board",
    )


async def notify_todo_reassigned(
    db: AsyncSession, todo: TodoItem, reassigned_by: HouseholdUser
) -> None:
    """Notifies whoever an admin just handed a board item straight to
    (crud.reassign_todo) — distinct wording from notify_todo_assigned's
    "asked you to", since reassign is a done deal, not a request to
    respond to."""
    if todo.assigned_to_id is None:
        return
    lang = await _recipient_language(db, todo.assigned_to_id)
    await _notify(
        db,
        todo.assigned_to_id,
        title=t(lang, "reassigned.title"),
        body=t(
            lang, "reassigned.body", admin=reassigned_by.display_name, todo=todo.title
        ),
        url="/board",
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
    # Local calendar date (HouseholdSettings.timezone), not UTC's — so
    # this agrees with run_scheduled_nudge_if_due's own local weekday/
    # hour check about which week is "this week." Mixing a local check
    # with a UTC week stamp here could double-send or skip a week right
    # around a local midnight that falls on the other side of the UTC
    # day boundary.
    local_today = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone)).date()
    week_start, _ = week_bounds(local_today, settings.week_start_weekday)
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
        lang = user.preferred_language
        body = (
            t(
                lang,
                "nudge.body_with_goal",
                points=points,
                goal=settings.weekly_points_goal,
            )
            if settings.weekly_points_goal is not None
            else t(lang, "nudge.body_no_goal")
        )
        # Always creates the in-app notification (see _notify), even
        # with no push subscription — `no_subscription` below still
        # measures push-delivery specifically, for the Admin panel's
        # "sent: N, skipped: N" summary, not whether the nudge is
        # visible at all.
        sent = await _notify(
            db, user.id, title=t(lang, "nudge.title"), body=body, url="/home"
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
    out — otherwise runs it and returns send_weekly_nudge's result.

    The weekday/hour check is against HouseholdSettings.timezone's
    local time, not raw UTC (same user report as the event-group
    schedule's own fix) — an admin picking "Monday at 18" means their
    own timezone's Monday 18:00, not UTC's. week_bounds also gets the
    local date, matching send_weekly_nudge's own basis for the week it
    stamps as sent, so the two can't disagree about which week this
    is right around a local midnight that falls on the other side of
    the UTC day boundary."""
    settings = await get_settings_row(db)
    if settings.nudge_weekday is None:
        return None
    local_now = datetime.now(UTC).astimezone(ZoneInfo(settings.timezone))
    if (
        local_now.weekday() != settings.nudge_weekday
        or local_now.hour != settings.nudge_hour
    ):
        return None
    week_start, _ = week_bounds(local_now.date(), settings.week_start_weekday)
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
        generated_by=generated_by.display_name if generated_by else None,
        generated_at=datetime.now(UTC),
        lang=settings.default_language,
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
    for admin in admins:
        lang = admin.preferred_language
        body = t(
            lang,
            "report_ready.body",
            period=t(lang, f"period.{report.period_type.value}"),
            start=report.period_start,
            end=report.period_end,
        )
        await _notify(
            db, admin.id, title=t(lang, "report_ready.title"), body=body, url="/admin"
        )
