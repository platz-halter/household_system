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

    # --- Auth ---------------------------------------------------------
    # "authentik": verify OIDC access tokens against Authentik's JWKS endpoint.
    # "local":     verify tokens issued by the local fallback auth service.
    auth_mode: Literal["authentik", "local"] = "authentik"

    authentik_issuer: str = (
        "https://authentik.pressnet.duckdns.org/application/o/household-system/"
    )
    authentik_jwks_url: str = (
        "https://authentik.pressnet.duckdns.org/application/o/household-system/jwks/"
    )
    authentik_client_id: str = ""

    # Used only when auth_mode == "local"; the local auth service signs its
    # own JWTs with this secret so other services can verify them the same
    # way they'd verify an Authentik token.
    local_jwt_secret: str = "dev-only-change-me"
    local_jwt_algorithm: str = "HS256"

    # --- Service-to-service -----------------------------------------
    auth_service_url: str = "http://auth:8000"

    # --- Misc -----------------------------------------------------------
    environment: Literal["dev", "prod"] = "dev"

    # --- CORS ---------------------------------------------------------
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def cors_origin_list(settings: Settings) -> list[str]:
    if settings.cors_origins.strip() == "*":
        return ["*"]
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
