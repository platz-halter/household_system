from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from shared.auth import CurrentUser, require_role
from shared.db import Base, engine

from fastapi.middleware.cors import CORSMiddleware
from shared.config import cors_origin_list, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only — replace with Alembic migrations before this
    # sees anything resembling production data.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Household System — Household (chores/points)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(get_settings()),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/me")
async def me(user: CurrentUser = Depends(require_role("admin", "user", "viewer"))):
    """Smoke-test route: confirms a bearer token from either Authentik or
    the local auth service resolves to a role correctly."""
    return {"subject": user.subject, "role": user.role, "source": user.source}


# TODO: routers for tasks, schedules, points, todo-board, categories, reports
