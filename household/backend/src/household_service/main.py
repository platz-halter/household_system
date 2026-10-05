import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from shared.auth import CurrentUser, require_role
from shared.config import cors_origin_list, get_settings
from shared.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from household_service import crud, scheduler
from household_service import reports as reports_pdf
from household_service.models import ReportPeriod, TakeoverStatus, TodoStatus
from household_service.schemas import (
    ActivityDay,
    BalancingRunResult,
    BalancingUserSummary,
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    ChainLinkIn,
    ChainLinkOut,
    ChainParentOut,
    HouseholdSettingsOut,
    HouseholdSettingsUpdate,
    HouseholdUserBrief,
    HouseholdUserOut,
    HouseholdUserUpdate,
    LeaderboardEntry,
    NotificationOut,
    NudgeResult,
    PointsEntryOut,
    PushSubscriptionIn,
    PushUnsubscribeIn,
    ReassignmentOut,
    ReportCreate,
    ReportMarkPaidIn,
    ReportOut,
    TakeoverRequestIn,
    TakeoverRequestOut,
    TaskAssignmentOut,
    TaskCompleteRequest,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TestPushResult,
    TodoCreate,
    TodoOut,
    TodoReassignIn,
    TodoUpdate,
    VapidPublicKeyOut,
)
from shared import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()


AVATAR_DIR = Path("/app/data/avatars")
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB — plenty for a profile photo

app = FastAPI(
    title="Household System — Household (chores/points)",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(get_settings()),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Same split as storage: viewers read-only, users/admins full use — the
# spec doesn't (yet) distinguish admin from user beyond that.
can_read = require_role("admin", "user", "viewer")
can_write = require_role("admin", "user")
# The weekly points goal is the one place this service distinguishes admin
# from user (see PROJECT_SPEC.md) — everything else stays flat per-role.
can_admin = require_role("admin")


async def _self(db: AsyncSession, user: CurrentUser):
    """Resolves (and auto-provisions) this request's HouseholdUser, and
    keeps its cached `role` hint in sync with the token's actual role —
    called on nearly every route, so in practice this stays fresh.
    `role` is never read for authorization (that's always the live token,
    same as everywhere else in this app) — it only exists so a
    background job (an auto-generated report) can know who's an admin to
    push-notify without a live request/token to check against."""
    household_user = await crud.get_or_create_household_user(db, user.subject)
    if household_user.role != user.role:
        household_user.role = user.role
        await db.commit()
        await db.refresh(household_user)
    return household_user


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__}


# ---- Current user / household users ---------------------------------


@app.get("/me", response_model=HouseholdUserOut)
async def me(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    return HouseholdUserOut.model_validate(await _self(db, user))


@app.patch("/me", response_model=HouseholdUserOut)
async def update_me(
    data: HouseholdUserUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    hu = await _self(db, user)
    return HouseholdUserOut.model_validate(
        await crud.update_household_user(db, hu, data)
    )


@app.get("/users", response_model=list[HouseholdUserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    return [
        HouseholdUserOut.model_validate(u) for u in await crud.list_household_users(db)
    ]


@app.post("/me/photo", response_model=HouseholdUserOut)
async def upload_my_photo(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type '{file.content_type}'. Allowed: {sorted(ALLOWED_IMAGE_TYPES)}",
        )

    contents = await file.read()
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit",
        )

    hu = await _self(db, user)
    old_filename = hu.image_path
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
        file.content_type
    ]
    filename = f"{hu.id}-{uuid.uuid4().hex}.{ext}"
    (AVATAR_DIR / filename).write_bytes(contents)

    result = HouseholdUserOut.model_validate(
        await crud.set_user_image(db, hu, filename)
    )
    if old_filename:
        (AVATAR_DIR / old_filename).unlink(missing_ok=True)
    return result


@app.delete("/me/photo", response_model=HouseholdUserOut)
async def delete_my_photo(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    hu = await _self(db, user)
    old_filename = hu.image_path
    result = HouseholdUserOut.model_validate(await crud.clear_user_image(db, hu))
    if old_filename:
        (AVATAR_DIR / old_filename).unlink(missing_ok=True)
    return result


@app.get("/users/{user_id}/photo")
async def get_user_photo(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    hu = await crud.get_household_user(db, user_id)
    if hu is None or not hu.image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No photo for this user"
        )
    path = AVATAR_DIR / hu.image_path
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image file missing on disk"
        )
    return FileResponse(path)


# ---- Categories -----------------------------------------------------


@app.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    return [CategoryOut.model_validate(c) for c in await crud.list_categories(db)]


@app.post(
    "/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED
)
async def create_category(
    data: CategoryIn,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    return CategoryOut.model_validate(await crud.create_category(db, data))


@app.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(
    category_id: int,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    category = await crud.get_category(db, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )
    return CategoryOut.model_validate(await crud.update_category(db, category, data))


@app.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    category = await crud.get_category(db, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )
    await crud.delete_category(db, category)


# ---- Tasks ------------------------------------------------------------


@app.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    active: bool | None = None,
    category_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    tasks = await crud.list_tasks(db, active=active, category_id=category_id)
    chain_child_ids = await crud.chain_child_task_ids(db)
    return [
        TaskOut.from_model(t, is_chain_child=t.id in chain_child_ids) for t in tasks
    ]


@app.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    data: TaskCreate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    try:
        task = await crud.create_task(db, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TaskOut.from_model(
        task, is_chain_child=await crud.is_chain_child(db, task.id)
    )


# Must stay declared before /tasks/{task_id} below, same reason as
# storage's /items/bulk* — otherwise FastAPI tries to parse
# "completions-today" as the {task_id} int path param instead.
@app.get("/tasks/completions-today", response_model=dict[int, int])
async def tasks_completions_today(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    return await crud.task_completions_today(db)


@app.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return TaskOut.from_model(
        task, is_chain_child=await crud.is_chain_child(db, task.id)
    )


@app.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: int,
    data: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    try:
        task = await crud.update_task(db, task, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TaskOut.from_model(
        task, is_chain_child=await crud.is_chain_child(db, task.id)
    )


# ---- Chain tasks --------------------------------------------------------


@app.get("/tasks/{task_id}/chain-links", response_model=list[ChainLinkOut])
async def list_chain_links(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    links = await crud.list_chain_links(db, task_id)
    return [ChainLinkOut.from_model(link) for link in links]


@app.get("/tasks/{task_id}/chain-parents", response_model=list[ChainParentOut])
async def list_chain_parents(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    """Which task(s) chain this one — the reverse of chain-links above.
    Used by the frontend to name them in the "already chained, complete
    it directly anyway?" confirm before completing a chain-child task
    with force=True (see TaskCompleteRequest)."""
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    links = await crud.list_chain_parents(db, task_id)
    return [ChainParentOut.from_model(link) for link in links]


@app.post(
    "/tasks/{task_id}/chain-links",
    response_model=ChainLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_chain_link(
    task_id: int,
    data: ChainLinkIn,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    try:
        link = await crud.create_chain_link(
            db,
            parent_task_id=task_id,
            child_task_id=data.child_task_id,
            same_user=data.same_user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return ChainLinkOut.from_model(link)


@app.delete(
    "/tasks/{task_id}/chain-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_chain_link(
    task_id: int,
    link_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    link = await crud.get_chain_link(db, link_id)
    if link is None or link.parent_task_id != task_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chain link not found"
        )
    await crud.delete_chain_link(db, link)


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    await crud.delete_task(db, task)


@app.post(
    "/tasks/{task_id}/complete",
    response_model=PointsEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def complete_task(
    task_id: int,
    body: TaskCompleteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    task = await crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    if not task.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not active"
        )

    override_id = body.household_user_id if body else None
    if override_id is not None:
        target = await crud.get_household_user(db, override_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="household_user_id not found",
            )
    else:
        target = await _self(db, user)

    try:
        entry = await crud.complete_task(
            db, task, target, force=body.force if body else False
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return PointsEntryOut.from_model(entry)


# ---- Todo board ---------------------------------------------------------


@app.get("/todos", response_model=list[TodoOut])
async def list_todos(
    todo_status: TodoStatus | None = Query(default=None, alias="status"),
    assigned_to_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    todos = await crud.list_todos(db, status=todo_status, assigned_to_id=assigned_to_id)
    return [TodoOut.from_model(t) for t in todos]


@app.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
async def create_todo(
    data: TodoCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    creator = await _self(db, user)
    try:
        todo = await crud.create_todo(db, data, creator)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await crud.notify_todo_assigned(db, todo, creator)
    return TodoOut.from_model(todo)


@app.patch("/todos/{todo_id}", response_model=TodoOut)
async def patch_todo(
    todo_id: int,
    data: TodoUpdate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    try:
        todo = await crud.update_todo(db, todo, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TodoOut.from_model(todo)


@app.post("/todos/{todo_id}/complete", response_model=TodoOut)
async def complete_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    if todo.status != TodoStatus.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Todo is already {todo.status.value}",
        )
    completer = await _self(db, user)
    return TodoOut.from_model(await crud.complete_todo(db, todo, completer))


@app.post("/todos/{todo_id}/cancel", response_model=TodoOut)
async def cancel_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    if todo.status != TodoStatus.open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Todo is already {todo.status.value}",
        )
    return TodoOut.from_model(await crud.cancel_todo(db, todo))


@app.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    await crud.delete_todo(db, todo)


@app.post("/todos/{todo_id}/claim", response_model=TodoOut)
async def claim_todo(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    if await crud.get_todo(db, todo_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    claimer = await _self(db, user)
    todo = await crud.claim_todo(db, todo_id, claimer)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item has already been claimed or assigned",
        )
    return TodoOut.from_model(todo)


@app.post("/todos/{todo_id}/reassign", response_model=TodoOut)
async def reassign_todo(
    todo_id: int,
    data: TodoReassignIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_admin),
):
    """Admin-only direct handoff — see crud.reassign_todo. Distinct from
    a takeover request below, which needs the target's consent."""
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    admin = await _self(db, user)
    try:
        todo = await crud.reassign_todo(db, todo, data.assigned_to_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await crud.notify_todo_reassigned(db, todo, admin)
    return TodoOut.from_model(todo)


# ---- Takeover requests -----------------------------------------------------


@app.post(
    "/todos/{todo_id}/takeover-requests",
    response_model=TakeoverRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_todo_takeover_request(
    todo_id: int,
    data: TakeoverRequestIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    todo = await crud.get_todo(db, todo_id)
    if todo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found"
        )
    requester = await _self(db, user)
    try:
        req = await crud.create_takeover_request_for_todo(
            db, todo, requester, data.target_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await crud.notify_takeover_requested(db, req)
    return TakeoverRequestOut.from_model(req)


@app.post(
    "/assignments/{assignment_id}/takeover-requests",
    response_model=TakeoverRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment_takeover_request(
    assignment_id: int,
    data: TakeoverRequestIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    assignment = await crud.get_task_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
        )
    requester = await _self(db, user)
    try:
        req = await crud.create_takeover_request_for_assignment(
            db, assignment, requester, data.target_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await crud.notify_takeover_requested(db, req)
    return TakeoverRequestOut.from_model(req)


@app.get("/takeover-requests", response_model=list[TakeoverRequestOut])
async def list_takeover_requests(
    direction: Literal["incoming", "outgoing"],
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    me = await _self(db, user)
    requests = await crud.list_takeover_requests(db, me.id, direction=direction)
    return [TakeoverRequestOut.from_model(r) for r in requests]


async def _get_own_takeover_request(
    db: AsyncSession, request_id: int, user: CurrentUser, *, as_target: bool
):
    req = await crud.get_takeover_request(db, request_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Takeover request not found"
        )
    me = await _self(db, user)
    owner_id = req.target_id if as_target else req.requester_id
    if owner_id != me.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your takeover request to respond to"
            if as_target
            else "Not your takeover request to cancel",
        )
    if req.status != TakeoverStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This request is already {req.status.value}",
        )
    return req


@app.post("/takeover-requests/{request_id}/accept", response_model=TakeoverRequestOut)
async def accept_takeover_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    req = await _get_own_takeover_request(db, request_id, user, as_target=True)
    try:
        req = await crud.accept_takeover_request(db, req)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    await crud.notify_takeover_responded(db, req)
    return TakeoverRequestOut.from_model(req)


@app.post("/takeover-requests/{request_id}/decline", response_model=TakeoverRequestOut)
async def decline_takeover_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    req = await _get_own_takeover_request(db, request_id, user, as_target=True)
    req = await crud.decline_takeover_request(db, req)
    await crud.notify_takeover_responded(db, req)
    return TakeoverRequestOut.from_model(req)


@app.post("/takeover-requests/{request_id}/cancel", response_model=TakeoverRequestOut)
async def cancel_takeover_request(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    req = await _get_own_takeover_request(db, request_id, user, as_target=False)
    req = await crud.cancel_takeover_request(db, req)
    return TakeoverRequestOut.from_model(req)


# ---- Task assignments / balancing tool -----------------------------------


@app.get("/assignments", response_model=list[TaskAssignmentOut])
async def list_assignments(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    assignments = await crud.list_current_assignments(db)
    return [TaskAssignmentOut.from_model(a) for a in assignments]


@app.post("/balancing/run", response_model=BalancingRunResult)
async def run_balancing(
    as_of: date | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    outcome = await crud.run_balancing(db, as_of=as_of)
    users_by_id = {u.id: u for u in await crud.list_household_users(db)}
    return BalancingRunResult(
        week_period_start=outcome.week_start,
        week_period_end=outcome.week_end,
        month_period_start=outcome.month_start,
        month_period_end=outcome.month_end,
        task_assignments=[
            TaskAssignmentOut.from_model(a) for a in outcome.new_task_assignments
        ],
        todo_assignments=[TodoOut.from_model(t) for t in outcome.new_todo_assignments],
        reassignments=[
            ReassignmentOut(
                task_name=row.task.name,
                points=pts,
                from_user=HouseholdUserBrief.model_validate(users_by_id[from_uid]),
                to_user=HouseholdUserBrief.model_validate(row.household_user),
            )
            for row, from_uid, _to_uid, pts in outcome.reassignments
        ],
        unassigned_task_count=outcome.unassigned_task_count,
        unassigned_todo_count=outcome.unassigned_todo_count,
        by_user=[
            BalancingUserSummary(
                household_user=HouseholdUserBrief.model_validate(t.user),
                new_task_count=t.new_task_count,
                new_todo_count=t.new_todo_count,
                new_expected_points=t.new_expected_points,
                reassigned_in_count=t.reassigned_in_count,
                reassigned_out_count=t.reassigned_out_count,
                reassigned_net_points=t.reassigned_net_points,
            )
            for t in outcome.user_summaries
        ],
    )


# ---- Points -------------------------------------------------------------


@app.get("/points/leaderboard", response_model=list[LeaderboardEntry])
async def points_leaderboard(
    since: datetime | None = None,
    until: datetime | None = None,
    # A convenience alternative to since/until: resolves server-side
    # (against the admin's configured week_start_weekday, in UTC) so
    # neither Home nor Stats needs its own date math — see
    # crud.resolve_leaderboard_bounds. since/until still work directly if
    # both are given; period is ignored in that case.
    period: Literal["all", "this_week", "last_week", "this_month"] | None = None,
    # Always resolved from the caller's own token, never a client-supplied
    # id — this only ever means "include me," not "include anyone I name."
    include_me: bool = False,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    if since is None and until is None and period is not None:
        since, until = await crud.resolve_leaderboard_bounds(db, period)
    include_user_id = None
    if include_me:
        include_user_id = (await _self(db, user)).id
    rows = await crud.leaderboard(
        db, since=since, until=until, include_user_id=include_user_id
    )
    return [
        LeaderboardEntry(user=HouseholdUserBrief.model_validate(u), total_points=total)
        for u, total in rows
    ]


@app.get("/points/recent", response_model=list[PointsEntryOut])
async def points_recent(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    return [
        PointsEntryOut.from_model(e) for e in await crud.recent_points(db, limit=limit)
    ]


@app.get("/points/activity", response_model=list[ActivityDay])
async def points_activity(
    since: date | None = None,
    until: date | None = None,
    household_user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    """Daily point totals for the GitHub-style activity heatmap. Defaults
    to the trailing year ending today; days with no activity are filled
    in as zero so the frontend can render a gap-free grid."""
    range_until = until or datetime.now(UTC).date()
    range_since = since or (range_until - timedelta(days=364))

    rows = dict(
        await crud.daily_activity(
            db,
            since=range_since,
            until=range_until,
            household_user_id=household_user_id,
        )
    )
    days = []
    cursor = range_since
    while cursor <= range_until:
        days.append(ActivityDay(date=cursor, points=rows.get(cursor, 0)))
        cursor += timedelta(days=1)
    return days


# ---- Settings -----------------------------------------------------------


@app.get("/settings", response_model=HouseholdSettingsOut)
async def get_settings_route(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    return HouseholdSettingsOut.model_validate(await crud.get_settings_row(db))


@app.put("/settings", response_model=HouseholdSettingsOut)
async def put_settings(
    data: HouseholdSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    return HouseholdSettingsOut.model_validate(await crud.update_settings(db, data))


# ---- Web Push -------------------------------------------------------------


@app.get("/push/vapid-public-key", response_model=VapidPublicKeyOut)
async def get_vapid_public_key(
    _user: CurrentUser = Depends(can_read),
):
    return VapidPublicKeyOut(public_key=get_settings().vapid_public_key or None)


@app.post("/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def push_subscribe(
    data: PushSubscriptionIn,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    hu = await _self(db, user)
    await crud.upsert_push_subscription(db, hu.id, data)


@app.post("/push/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def push_unsubscribe(
    data: PushUnsubscribeIn,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_write),
):
    await crud.remove_push_subscription(db, data.endpoint)


@app.post("/push/nudge", response_model=NudgeResult)
async def push_nudge(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    """Admin-triggered weekly reminder — see crud.send_weekly_nudge for why
    this is a manual button rather than an automatic schedule. This only
    reaches people below their weekly goal — use POST /push/test to check
    delivery works at all, regardless of anyone's points."""
    notified, already_met_goal, no_subscription = await crud.send_weekly_nudge(db)
    return NudgeResult(
        notified=notified,
        skipped_already_met_goal=already_met_goal,
        skipped_no_subscription=no_subscription,
    )


@app.post("/push/test", response_model=TestPushResult)
async def push_test(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_write),
):
    """Sends yourself an unconditional test push — unlike /push/nudge,
    this ignores break/goal status, so it actually proves whether
    delivery works for your own subscription(s)."""
    hu = await _self(db, user)
    sent = await crud.send_test_push(db, hu.id)
    return TestPushResult(sent=sent)


# ---- Notification inbox ----------------------------------------------------


@app.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    me = await _self(db, user)
    items = await crud.list_notifications(
        db, me.id, unread_only=unread_only, limit=limit
    )
    return [NotificationOut.model_validate(n) for n in items]


@app.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    me = await _self(db, user)
    notification = await crud.get_notification(db, notification_id)
    if notification is None or notification.household_user_id != me.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    notification = await crud.mark_notification_read(db, notification)
    return NotificationOut.model_validate(notification)


@app.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_read),
):
    me = await _self(db, user)
    await crud.mark_all_notifications_read(db, me.id)


# ---- Reports --------------------------------------------------------------


async def _last_week_start(db: AsyncSession) -> date:
    settings = await crud.get_settings_row(db)
    this_week_start, _ = crud.week_bounds(
        datetime.now(UTC).date(), settings.week_start_weekday
    )
    return this_week_start - timedelta(days=7)


@app.get("/reports", response_model=list[ReportOut])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    last_week_start = await _last_week_start(db)
    return [
        ReportOut.from_model(
            r,
            is_last_week=r.period_type == ReportPeriod.week
            and r.period_start == last_week_start,
        )
        for r in await crud.list_reports(db)
    ]


@app.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    data: ReportCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(can_admin),
):
    generator = await _self(db, user)
    report = await crud.create_report(db, data, generator)
    await crud.notify_new_report(db, report, exclude_user_id=generator.id)
    last_week_start = await _last_week_start(db)
    return ReportOut.from_model(
        report,
        is_last_week=report.period_type == ReportPeriod.week
        and report.period_start == last_week_start,
    )


@app.patch("/reports/{report_id}", response_model=ReportOut)
async def patch_report(
    report_id: int,
    data: ReportMarkPaidIn,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    report = await crud.get_report(db, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )
    report = await crud.mark_report_paid(db, report, data.paid)
    last_week_start = await _last_week_start(db)
    return ReportOut.from_model(
        report,
        is_last_week=report.period_type == ReportPeriod.week
        and report.period_start == last_week_start,
    )


@app.get("/reports/{report_id}/download")
async def download_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_admin),
):
    report = await crud.get_report(db, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        )
    path = reports_pdf.REPORTS_DIR / report.file_path
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report file missing on disk"
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)
