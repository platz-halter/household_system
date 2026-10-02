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


def _send_one(subscription: PushSubscription, payload: dict) -> bool:
    """Returns False if the push service says this subscription is gone
    (404/410 — should be deleted), True otherwise (sent, or a transient
    failure not worth deleting the subscription over)."""
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
        )
        return True
    except WebPushException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (404, 410):
            return False
        logger.warning("Push to %s failed: %s", subscription.endpoint, exc)
        return True


async def send_to_subscriptions(
    db: AsyncSession, subscriptions: list[PushSubscription], payload: dict
) -> int:
    """Sends `payload` to every subscription, pruning any the push service
    reports as gone. Returns how many sends were attempted-and-not-dead
    (not a delivery guarantee — the push service queues it best-effort)."""
    settings = get_settings()
    if not settings.vapid_private_key:
        logger.warning("VAPID keys not configured — skipping push send")
        return 0

    sent = 0
    for sub in subscriptions:
        alive = await asyncio.to_thread(_send_one, sub, payload)
        if alive:
            sent += 1
        else:
            await db.delete(sub)
    if subscriptions:
        await db.commit()
    return sent
