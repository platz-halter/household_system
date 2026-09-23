from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.models import LocalUser
from auth_service.security import create_local_access_token, verify_password
from shared.db import Base, engine, get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience only — replace with Alembic migrations before this
    # sees anything resembling production data.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Household System — Auth (local fallback)", lifespan=lifespan)


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
    result = await db.execute(select(LocalUser).where(LocalUser.username == form_data.username))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = create_local_access_token(subject=user.username, role=user.role)
    return {"access_token": token, "token_type": "bearer"}
