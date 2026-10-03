"""Token verification shared by every backend.

Downstream services (household, storage) never need to know whether a
request was authenticated via Authentik or the local fallback service —
they just call `get_current_user`, which always returns the same
`CurrentUser` shape. Both verification paths are ALWAYS available; which
one runs is decided per-request from the token's own signing algorithm
(local tokens are HS256, Authentik's are RS256) rather than a global
setting. That's what actually makes local accounts a fallback: you can
log in locally when Authentik is unreachable without redeploying
anything, and an Authentik session from someone else keeps working at
the same time.

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
    "household-system-admins": "admin",
    "household-system-users": "user",
    "household-system-viewers": "viewer",
}


@dataclass
class CurrentUser:
    subject: str  # stable user id / username
    role: Role
    source: Literal["authentik", "local"]


def _env_fallback_config() -> dict[str, str]:
    """The seven fields' static env/.env-sourced values — used as a
    last resort if the auth service's /authentik-config has never been
    reachable yet (e.g. this service started before auth did)."""
    return {
        "issuer": settings.authentik_issuer,
        "jwks_url": settings.authentik_jwks_url,
        "client_id": settings.authentik_client_id,
        "authorize_url": settings.authentik_authorize_url,
        "token_url": settings.authentik_token_url,
        "end_session_url": settings.authentik_end_session_url,
        "scope": settings.authentik_scope,
    }


class _AuthentikConfigCache:
    """Polls the auth service's `GET /authentik-config` (the one place
    an admin-saved override actually lives — see auth_service.main) with
    a short TTL, so a change made through the admin panel reaches every
    service's token verification within this TTL, without a restart.

    Every service calls this the SAME way, including the auth service
    itself (over its own `auth:8000` network alias) — that keeps this
    logic in exactly one place rather than special-casing "the service
    that owns the data doesn't need to ask over HTTP."

    An unreachable auth service must never take down Authentik
    verification everywhere else: falls back to the last value this
    process successfully fetched, or to the static env defaults if it
    has never fetched successfully at all.
    """

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._ttl = ttl_seconds
        self._fetched_at: float = 0.0
        self._config: dict[str, str] | None = None

    async def get(self) -> dict[str, str]:
        now = time.monotonic()
        if self._config is None or (now - self._fetched_at) > self._ttl:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{settings.auth_service_url}/authentik-config"
                    )
                    resp.raise_for_status()
                    self._config = resp.json()
                    self._fetched_at = now
            except httpx.HTTPError:
                if self._config is None:
                    self._config = _env_fallback_config()
                # else: keep serving the last-known-good config until the
                # auth service is reachable again.
        return self._config


_authentik_config_cache = _AuthentikConfigCache()


class _JWKSCache:
    """Tiny TTL cache so we don't hit Authentik's JWKS endpoint on every
    request. Keyed by jwks_url (not a single global slot) — the URL
    itself can change via the admin panel, and keying by it means a
    change takes effect immediately instead of still serving keys
    fetched from the OLD url for up to `ttl_seconds` after the switch."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, jwks_url: str) -> dict[str, Any]:
        now = time.monotonic()
        entry = self._cache.get(jwks_url)
        if entry is not None and (now - entry[0]) <= self._ttl:
            return entry[1]
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            keys = resp.json()
        self._cache[jwks_url] = (now, keys)
        return keys


_jwks_cache = _JWKSCache()


def _role_from_groups(groups: list[str]) -> Role:
    for group in groups:
        if group in GROUP_ROLE_MAP:
            return GROUP_ROLE_MAP[group]
    # Default to the least-privileged role if the token carries no
    # recognised group — fail closed, not open.
    return "viewer"


async def _verify_authentik_token(token: str) -> CurrentUser:
    config = await _authentik_config_cache.get()
    try:
        jwks = await _jwks_cache.get(config["jwks_url"])
    except httpx.HTTPError as exc:
        # An unreachable Authentik (or a jwks_url an admin just typo'd)
        # must surface as a clean, ordinary-looking failure, not an
        # unhandled exception FastAPI would otherwise turn into a bare 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach Authentik to verify this token",
        ) from exc

    try:
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=config["client_id"],
            issuer=config["issuer"],
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


def _peek_algorithm(token: str) -> str | None:
    """Reads the 'alg' header WITHOUT verifying the signature — used only
    to decide which verifier to run. The chosen verifier still checks the
    signature properly; this never grants trust by itself."""
    try:
        return jwt.get_unverified_header(token).get("alg")
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    token = credentials.credentials
    alg = _peek_algorithm(token)

    if alg == settings.local_jwt_algorithm:
        return _verify_local_token(token)
    if alg == "RS256":
        return await _verify_authentik_token(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unrecognized token signing algorithm",
    )


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
