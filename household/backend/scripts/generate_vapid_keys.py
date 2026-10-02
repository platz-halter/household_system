"""One-off: generate a VAPID keypair for Web Push and print .env lines.

Run once per deployment (not per restart — these are long-lived keys that
identify this server to push services):

    uv run --package household-backend python household/backend/scripts/generate_vapid_keys.py

Paste the output into .env. VAPID_PUBLIC_KEY is not a secret (it's handed
to every browser as applicationServerKey); VAPID_PRIVATE_KEY is.
"""

import base64

from py_vapid import Vapid01


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    print(
        "VAPID_PRIVATE_KEY="
        + base64.urlsafe_b64encode(private_raw).decode().rstrip("=")
    )

    pub = vapid.public_key.public_numbers()
    raw_public = b"\x04" + pub.x.to_bytes(32, "big") + pub.y.to_bytes(32, "big")
    print(
        "VAPID_PUBLIC_KEY=" + base64.urlsafe_b64encode(raw_public).decode().rstrip("=")
    )


if __name__ == "__main__":
    main()
