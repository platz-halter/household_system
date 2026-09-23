"""Token verification shared by every backend.

Downstream services (household, storage) never need to know whether a
request was authenticated via Authentik or the local fallback service —
they just call `get_current_user`. It dispatches on `settings.auth_mode`
and always returns the same `CurrentUser` shape.

Role mapping (Authentik groups -> app role) happens once, here, so it's
defined in exactly one place rather than duplicated per service.
"""

import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from shared.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=True)

Role = Literal["admin", "user", "viewer"]

# Authentik group name -> app role. Adjust to match the svc-<app> groups
# actually created for this application in Authentik.
GROUP_ROLE_MAP: dict[str, Role] = {
    "svc-household-system-admins": "admin",
    "svc-household-system-users": "user",
    "svc-household-system-viewers": "viewer",
}


@dataclass
class CurrentUser:
    subject: str  # stable user id / username
    role: Role
    source: Literal["authentik", "local"]


class _JWKSCache:
    """Tiny TTL cache so we don't hit Authentik's JWKS endpoint on every request."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._fetched_at: float = 0.0
        self._keys: dict[str, Any] | None = None

    async def get(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._keys is None or (now - self._fetched_at) > self._ttl:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(settings.authentik_jwks_url)
                resp.raise_for_status()
                self._keys = resp.json()
                self._fetched_at = now
        return self._keys


_jwks_cache = _JWKSCache()


def _role_from_groups(groups: list[str]) -> Role:
    for group in groups:
        if group in GROUP_ROLE_MAP:
            return GROUP_ROLE_MAP[group]
    # Default to the least-privileged role if the token carries no
    # recognised group — fail closed, not open.
    return "viewer"


async def _verify_authentik_token(token: str) -> CurrentUser:
    jwks = await _jwks_cache.get()
    try:
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.authentik_client_id,
            issuer=settings.authentik_issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    groups = claims.get("groups", [])
    return CurrentUser(
        subject=claims.get("preferred_username", claims["sub"]),
        role=_role_from_groups(groups),
        source="authentik",
    )


def _verify_local_token(token: str) -> CurrentUser:
    try:
        claims = jwt.decode(
            token,
            settings.local_jwt_secret,
            algorithms=[settings.local_jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    role: Role = claims.get("role", "viewer")
    return CurrentUser(subject=claims["sub"], role=role, source="local")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    token = credentials.credentials
    if settings.auth_mode == "authentik":
        return await _verify_authentik_token(token)
    return _verify_local_token(token)


def require_role(*allowed: Role):
    """Dependency factory: `Depends(require_role("admin", "user"))`."""

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to perform this action",
            )
        return user

    return _check
