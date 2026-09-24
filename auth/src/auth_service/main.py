from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.models import LocalUser
from auth_service.security import (
    create_local_access_token,
    hash_password,
    verify_password,
)
from shared.auth import CurrentUser, require_role
from shared.config import cors_origin_list, get_settings
from shared.db import Base, engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only — replace with Alembic migrations before this
    # sees anything resembling production data.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Household System — Auth (local fallback)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(get_settings()),
    allow_credentials=False,  # no cookies used — just a bearer token header
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/token")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Local-account login. Only relevant for dev/testing or when
    Authentik is unreachable — normal usage should authenticate against
    Authentik directly and never hit this service."""
    result = await db.execute(
        select(LocalUser).where(LocalUser.username == form_data.username)
    )
    user = result.scalar_one_or_none()

    if (
        user is None
        or not user.is_active
        or not verify_password(form_data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = create_local_access_token(subject=user.username, role=user.role)
    return {"access_token": token, "token_type": "bearer"}


class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    role: Literal["admin", "user", "viewer"] = "viewer"


class UserOut(BaseModel):
    username: str
    role: str
    is_active: bool


@app.post(
    "/bootstrap-admin", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
async def bootstrap_admin(new_user: NewUser, db: AsyncSession = Depends(get_db)):
    """One-time, unauthenticated: creates the first admin account. Only
    works while `local_users` is empty — closes itself off immediately
    after, so it can't be used to create a second admin or be abused
    once the system is actually in use."""
    count = await db.scalar(select(func.count()).select_from(LocalUser))
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bootstrap already used — a local user already exists. Use POST /users (admin auth) instead.",
        )

    user = LocalUser(
        username=new_user.username,
        hashed_password=hash_password(new_user.password),
        role="admin",  # bootstrap always creates an admin, regardless of what's requested
    )
    db.add(user)
    await db.commit()
    return UserOut(username=user.username, role=user.role, is_active=user.is_active)


@app.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    new_user: NewUser,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_role("admin")),
):
    """Admin-only: create additional local users after bootstrap."""
    existing = await db.execute(
        select(LocalUser).where(LocalUser.username == new_user.username)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        )

    user = LocalUser(
        username=new_user.username,
        hashed_password=hash_password(new_user.password),
        role=new_user.role,
    )
    db.add(user)
    await db.commit()
    return UserOut(username=user.username, role=user.role, is_active=user.is_active)
