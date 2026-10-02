"""Common settings shared by every backend service.

Each service imports `get_settings()` and gets its own values from
environment variables (set per-container in docker-compose.yml), so one
class definition covers auth, household and storage without duplication.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---------------------------------------------------
    database_url: str = "postgresql+asyncpg://hs_admin:changeme@localhost:5432/postgres"

    # --- Auth -----------------------------------------------------------
    # Both verification paths below are always active (see shared/auth.py)
    # — which one runs is decided per-token, not by a mode switch here.

    authentik_issuer: str = "https://authentik.pressnet.duckdns.org/application/o/household-system/"
    authentik_jwks_url: str = (
        "https://authentik.pressnet.duckdns.org/application/o/household-system/jwks/"
    )
    authentik_client_id: str = ""

    # The local auth service signs its own JWTs with this secret so other
    # services can verify them the same way they'd verify an Authentik
    # token — just a different algorithm/key.
    local_jwt_secret: str = "dev-only-change-me"
    local_jwt_algorithm: str = "HS256"

    # --- Service-to-service -----------------------------------------
    auth_service_url: str = "http://auth:8000"

    # --- Web Push (household service only) ---------------------------
    # Generate a pair with:
    #   uv run --package household-backend python household/backend/scripts/generate_vapid_keys.py
    # VAPID_PUBLIC_KEY is also handed to the frontend as-is (applicationServerKey).
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # --- CORS ---------------------------------------------------------
    # Comma-separated list of allowed origins, or "*" for any (default —
    # fine here since no cookies are used, only a bearer token header).
    # Once everything sits behind Caddy on one origin, CORS won't even
    # be exercised by the browser — but set this to your actual
    # frontend origin(s) if you ever serve the frontend from a
    # different origin than the one Caddy proxies /api/* on.
    cors_origins: str = "*"

    # --- Misc -----------------------------------------------------------
    environment: Literal["dev", "prod"] = "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def cors_origin_list(settings: Settings) -> list[str]:
    if settings.cors_origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
