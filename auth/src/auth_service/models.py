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
    panel.

    `admin_group`/`user_group`/`viewer_group` are the Authentik group
    *names* that map to each app role — previously a hardcoded dict
    (`shared.auth.GROUP_ROLE_MAP`) that needed a source edit + rebuild
    + redeploy of every backend plus the storage frontend to change.
    `shared.auth._role_from_groups` now reads these the same
    cached-and-polled way as the other seven fields; see its own
    docstring for the one piece that's still a static, UI-only mirror
    (both frontends' `ROLE_FROM_GROUPS`, for client-side role display
    only — never used for actual authorization)."""

    __tablename__ = "authentik_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    issuer: Mapped[str] = mapped_column(String(512))
    jwks_url: Mapped[str] = mapped_column(String(512))
    client_id: Mapped[str] = mapped_column(String(255))
    authorize_url: Mapped[str] = mapped_column(String(512))
    token_url: Mapped[str] = mapped_column(String(512))
    end_session_url: Mapped[str] = mapped_column(String(512))
    scope: Mapped[str] = mapped_column(String(255))
    admin_group: Mapped[str] = mapped_column(
        String(255), server_default="household-system-admins"
    )
    user_group: Mapped[str] = mapped_column(
        String(255), server_default="household-system-users"
    )
    viewer_group: Mapped[str] = mapped_column(
        String(255), server_default="household-system-viewers"
    )
