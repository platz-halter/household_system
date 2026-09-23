from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from shared.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_TTL = timedelta(hours=12)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_local_access_token(subject: str, role: str) -> str:
    """Issue a JWT in the same shape `shared.auth._verify_local_token`
    expects — kept in the auth service since it's the only thing that
    should ever sign these."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(
        claims, settings.local_jwt_secret, algorithm=settings.local_jwt_algorithm
    )
