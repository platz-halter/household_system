from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


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
