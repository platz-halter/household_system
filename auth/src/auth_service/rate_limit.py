"""A small in-memory lockout for POST /token, so repeatedly guessing a
local account's password isn't free. Deliberately simple — this project
targets a handful of real users on a homelab, not an internet-facing
service, so a hand-rolled in-memory tracker is enough; no Redis or other
shared store needed, and `shared/entrypoint.sh` runs exactly one uvicorn
worker per service, so this process-local state is authoritative.
"""

import time

from fastapi import HTTPException, status

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60
# Bounds memory if someone sprays many distinct usernames at /token
# instead of repeating one — a real deployment at this project's scale
# (a handful of actual accounts) will never come close to this.
MAX_TRACKED_USERNAMES = 10_000


class LoginRateLimiter:
    """Keyed by the USERNAME being attempted, not the client's IP.

    Requests reach this service through two reverse-proxy hops (Caddy,
    then this container's own nginx — see storage/household frontend
    nginx.conf), and getting the real client IP right through both
    isn't guaranteed to be configured correctly in every deployment.
    Keying on the targeted account instead directly matches the actual
    threat — repeated password guessing against one account — and
    doesn't depend on proxy headers being set up right to actually
    work. The tradeoff: this can't distinguish many attackers hammering
    one account from one attacker spraying many accounts a few times
    each; acceptable at this project's scale (see module docstring).
    """

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        window_seconds: int = WINDOW_SECONDS,
        max_tracked: int = MAX_TRACKED_USERNAMES,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._max_tracked = max_tracked
        self._failures: dict[str, list[float]] = {}

    def check(self, username: str) -> None:
        """Raises 429 if `username` has hit the failure cap within the
        current window. Call before verifying the password, so a
        locked-out account can't be used to keep guessing at all."""
        attempts = self._failures.get(username)
        if not attempts:
            return
        now = time.monotonic()
        attempts[:] = [t for t in attempts if now - t < self._window]
        if len(attempts) >= self._max_attempts:
            retry_after = max(1, int(self._window - (now - attempts[0])))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts for this account. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    def record_failure(self, username: str) -> None:
        if username not in self._failures and len(self._failures) >= self._max_tracked:
            # Evict the oldest-inserted entry to bound memory. Not a
            # perfect eviction policy, but simple, and a legitimate
            # deployment never comes close to this cap — see module
            # docstring.
            oldest = next(iter(self._failures))
            del self._failures[oldest]
        self._failures.setdefault(username, []).append(time.monotonic())

    def record_success(self, username: str) -> None:
        self._failures.pop(username, None)


login_rate_limiter = LoginRateLimiter()
