"""Web Push sending — a thin wrapper around pywebpush so callers don't need
to juggle VAPID claims or dead-subscription cleanup themselves.

pywebpush/requests are synchronous (blocking network I/O); each send runs
in a worker thread via asyncio.to_thread so it doesn't stall the event
loop. Fine at this app's scale (a handful of users, a handful of devices
each) — not written for fan-out to many recipients.
"""

import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from shared.config import get_settings
from sqlalchemy.ext.asyncio import AsyncSession

from household_service.models import PushSubscription

logger = logging.getLogger(__name__)


def _send_one(subscription: PushSubscription, payload: dict) -> str:
    """Returns "sent" (the push service accepted it), "gone" (404/410 —
    the subscription should be deleted), or "failed" (anything else — a
    real delivery failure, but not necessarily proof the subscription
    itself is dead, so it's kept rather than deleted).

    Earlier version of this bug: any non-404/410 WebPushException was
    treated as "sent" just because it wasn't a dead subscription — which
    silently counted real failures (bad VAPID claim, 4xx/5xx from the
    push service, etc.) as successful deliveries. That's what made the
    Admin panel's test/nudge buttons look like they worked when nothing
    actually arrived.

    `timeout`: pywebpush passes this straight through to the underlying
    `requests.post()`, which has NO default timeout of its own — without
    this, one slow or unreachable push endpoint (a push service having
    an outage, a network blip) hangs this call, and everything awaiting
    it, for however long the OS-level TCP timeout happens to be (minutes,
    not seconds — caught live: a stale subscription in a sandboxed dev
    environment with restricted container egress hung an admin-reassign
    request for 2+ minutes). A single slow subscription shouldn't be
    able to make an unrelated API request hang this long."""
    settings = get_settings()
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            timeout=10,
        )
        return "sent"
    except WebPushException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (404, 410):
            return "gone"
        logger.warning(
            "Push to %s failed (status=%s): %s", subscription.endpoint, status_code, exc
        )
        return "failed"
    except Exception as exc:  # noqa: BLE001 - network/transport errors from the
        # underlying requests call aren't always wrapped in WebPushException;
        # never let one bad subscription take down the whole send loop.
        logger.warning("Push to %s raised unexpectedly: %s", subscription.endpoint, exc)
        return "failed"


async def send_to_subscriptions(
    db: AsyncSession, subscriptions: list[PushSubscription], payload: dict
) -> int:
    """Sends `payload` to every subscription, pruning any the push service
    reports as gone. Returns how many were actually accepted by the push
    service (not a delivery guarantee beyond that — it queues best-effort
    from there — but unlike before, a real failure is no longer counted
    as a success)."""
    settings = get_settings()
    if not settings.vapid_private_key:
        logger.warning("VAPID keys not configured — skipping push send")
        return 0

    sent = 0
    for sub in subscriptions:
        result = await asyncio.to_thread(_send_one, sub, payload)
        if result == "sent":
            sent += 1
        elif result == "gone":
            await db.delete(sub)
        # "failed": leave the subscription in place, don't count it as sent.
    if subscriptions:
        await db.commit()
    return sent
