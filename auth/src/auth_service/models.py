from shared.db import Base
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column


class LocalUser(Base):
    """A local-only account, used for dev/testing or as a fallback when
    Authentik isn't reachable. Lives only in the `auth` database — never
    synced with Authentik."""

    __tablename__ = "local_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # Matches shared.auth.Role ("admin" | "user" | "viewer")
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    is_active: Mapped[bool] = mapped_column(default=True)


class AuthentikSettings(Base):
    """Singleton row (same pattern as household's `HouseholdSettings`) —
    the live, admin-editable Authentik connection config. An admin saves
    this through the panel instead of hand-editing `.env` + both
    frontends' `config.js`. Every service (including this one, over its
    own network alias — see `shared.auth._AuthentikConfigCache`) reads
    the current value through `GET /authentik-config`, which falls back
    to the static env defaults in `shared/config.py` while this table
    is empty, so a fresh deploy still works before anyone touches the
    panel."""

    __tablename__ = "authentik_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(512))
    jwks_url: Mapped[str] = mapped_column(String(512))
    client_id: Mapped[str] = mapped_column(String(255))
    authorize_url: Mapped[str] = mapped_column(String(512))
    token_url: Mapped[str] = mapped_column(String(512))
    end_session_url: Mapped[str] = mapped_column(String(512))
    scope: Mapped[str] = mapped_column(String(255))
