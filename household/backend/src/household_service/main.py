from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.auth import CurrentUser, require_role
from shared.config import cors_origin_list, get_settings


app = FastAPI(title="Household System — Household (chores/points)")

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
