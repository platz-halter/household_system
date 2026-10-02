from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from shared.auth import CurrentUser, require_role
from shared.config import cors_origin_list, get_settings
from shared.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from household_service import crud
from household_service.models import TodoStatus
from household_service.schemas import (
    CategoryIn,
    CategoryOut,
    CategoryUpdate,
    HouseholdSettingsOut,
    HouseholdSettingsUpdate,
    HouseholdUserBrief,
    HouseholdUserOut,
    HouseholdUserUpdate,
    LeaderboardEntry,
    PointsEntryOut,
    TaskCompleteRequest,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TodoCreate,
    TodoOut,
    TodoUpdate,
)

app = FastAPI(title="Household System — Household (chores/points)")

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


async def _self(db: AsyncSession, user: CurrentUser):
    return await crud.get_or_create_household_user(db, user.subject)


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    return [TaskOut.from_model(t) for t in tasks]


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
    return TaskOut.from_model(task)


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
    return TaskOut.from_model(task)


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
    return TaskOut.from_model(task)


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

    entry = await crud.complete_task(db, task, target)
    return PointsEntryOut.model_validate(entry)


# ---- Todo board ---------------------------------------------------------


@app.get("/todos", response_model=list[TodoOut])
async def list_todos(
    todo_status: TodoStatus | None = Query(default=None, alias="status"),
    assigned_to_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    todos = await crud.list_todos(db, status=todo_status, assigned_to_id=assigned_to_id)
    return [TodoOut.model_validate(t) for t in todos]


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
    return TodoOut.model_validate(todo)


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
    return TodoOut.model_validate(todo)


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
    return TodoOut.model_validate(await crud.complete_todo(db, todo, completer))


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
    return TodoOut.model_validate(await crud.cancel_todo(db, todo))


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


# ---- Points -------------------------------------------------------------


@app.get("/points/leaderboard", response_model=list[LeaderboardEntry])
async def points_leaderboard(
    since: datetime | None = None,
    until: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(can_read),
):
    rows = await crud.leaderboard(db, since=since, until=until)
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
        PointsEntryOut.model_validate(e)
        for e in await crud.recent_points(db, limit=limit)
    ]


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
    _user: CurrentUser = Depends(can_write),
):
    return HouseholdSettingsOut.model_validate(await crud.update_settings(db, data))
