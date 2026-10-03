from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from shared.auth import CurrentUser, require_role
from shared.config import cors_origin_list, get_settings
from shared.db import get_db
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.models import AuthentikSettings, LocalUser
from auth_service.security import (
    create_local_access_token,
    hash_password,
    verify_password,
)

app = FastAPI(title="Household System — Auth (local fallback)")

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


class AuthentikConfigOut(BaseModel):
    issuer: str
    jwks_url: str
    client_id: str
    authorize_url: str
    token_url: str
    end_session_url: str
    scope: str


class AuthentikConfigIn(AuthentikConfigOut):
    # Proves the caller holds a LOCAL admin's password, not just a
    # currently-valid admin bearer token — see _check_reauth below.
    reauth_username: str
    reauth_password: str


class AuthentikReauthIn(BaseModel):
    reauth_username: str
    reauth_password: str


def _env_fallback_authentik_config() -> AuthentikConfigOut:
    s = get_settings()
    return AuthentikConfigOut(
        issuer=s.authentik_issuer,
        jwks_url=s.authentik_jwks_url,
        client_id=s.authentik_client_id,
        authorize_url=s.authentik_authorize_url,
        token_url=s.authentik_token_url,
        end_session_url=s.authentik_end_session_url,
        scope=s.authentik_scope,
    )


@app.get("/authentik-config", response_model=AuthentikConfigOut)
async def get_authentik_config(db: AsyncSession = Depends(get_db)):
    """Public — not a secret. These seven values already ship to every
    browser today (both frontends' `config.js` used to hardcode them),
    and are equally discoverable from Authentik's own `.well-known`
    document. Every service — this one included, calling itself over
    its own `auth:8000` network alias, see `shared.auth
    ._AuthentikConfigCache` — polls this to learn whatever an admin has
    saved through the panel, without needing a restart to pick it up."""
    row = await db.scalar(select(AuthentikSettings).limit(1))
    if row is None:
        return _env_fallback_authentik_config()
    return AuthentikConfigOut(
        issuer=row.issuer,
        jwks_url=row.jwks_url,
        client_id=row.client_id,
        authorize_url=row.authorize_url,
        token_url=row.token_url,
        end_session_url=row.end_session_url,
        scope=row.scope,
    )


async def _check_reauth(db: AsyncSession, username: str, password: str) -> None:
    """Whoever can repoint `issuer`/`jwks_url` at a JWKS they control can
    mint tokens every service in the system would accept as an admin —
    access that would outlive the bearer token used to call this
    endpoint, and survive a password change on whatever account that
    token belonged to. A deliberately-entered LOCAL admin password is
    the actual check for that, independent of whatever bearer token
    `require_role("admin")` already accepted — and it keeps working
    even when Authentik itself is what's broken, which is exactly when
    this panel gets used."""
    result = await db.execute(select(LocalUser).where(LocalUser.username == username))
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.role != "admin"
        or not verify_password(password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Re-authentication failed"
        )


async def _validate_issuer(issuer: str, jwks_url: str) -> None:
    """Rejects an issuer/jwks_url that doesn't check out against the
    IdP's own discovery document, so a typo can't lock every admin out
    of Authentik login at once — caught here, before saving, instead of
    on the next real login attempt."""
    issuer_clean = issuer.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            discovery = await client.get(
                f"{issuer_clean}/.well-known/openid-configuration"
            )
            discovery.raise_for_status()
            doc = discovery.json()
            if doc.get("issuer", "").rstrip("/") != issuer_clean:
                raise ValueError(
                    "the issuer's own discovery document reports a different issuer"
                )
            jwks_resp = await client.get(doc.get("jwks_uri") or jwks_url)
            jwks_resp.raise_for_status()
            if not jwks_resp.json().get("keys"):
                raise ValueError("no signing keys found at jwks_uri")
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not validate this issuer: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@app.put("/authentik-config", response_model=AuthentikConfigOut)
async def put_authentik_config(
    body: AuthentikConfigIn,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_role("admin")),
):
    """Admin-only AND reauth-gated (see _check_reauth) — this single
    write effectively controls who every service in the system trusts
    as an admin, so a currently-valid bearer token alone is not enough
    to change it."""
    await _check_reauth(db, body.reauth_username, body.reauth_password)
    await _validate_issuer(body.issuer, body.jwks_url)

    row = await db.scalar(select(AuthentikSettings).limit(1))
    if row is None:
        row = AuthentikSettings(
            issuer=body.issuer,
            jwks_url=body.jwks_url,
            client_id=body.client_id,
            authorize_url=body.authorize_url,
            token_url=body.token_url,
            end_session_url=body.end_session_url,
            scope=body.scope,
        )
        db.add(row)
    else:
        row.issuer = body.issuer
        row.jwks_url = body.jwks_url
        row.client_id = body.client_id
        row.authorize_url = body.authorize_url
        row.token_url = body.token_url
        row.end_session_url = body.end_session_url
        row.scope = body.scope
    await db.commit()
    return AuthentikConfigOut(
        issuer=row.issuer,
        jwks_url=row.jwks_url,
        client_id=row.client_id,
        authorize_url=row.authorize_url,
        token_url=row.token_url,
        end_session_url=row.end_session_url,
        scope=row.scope,
    )


@app.post("/authentik-config/reset", response_model=AuthentikConfigOut)
async def reset_authentik_config(
    body: AuthentikReauthIn,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentUser = Depends(require_role("admin")),
):
    """Deletes the saved override row, reverting every service to the
    static `.env` defaults. Same reauth requirement as PUT — changing
    live auth config either direction is the same class of risk."""
    await _check_reauth(db, body.reauth_username, body.reauth_password)
    row = await db.scalar(select(AuthentikSettings).limit(1))
    if row is not None:
        await db.delete(row)
        await db.commit()
    return _env_fallback_authentik_config()
