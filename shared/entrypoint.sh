#!/bin/sh
# Shared container entrypoint for every backend service: apply this
# service's database migrations, THEN start the API.
#
#   entrypoint.sh <uv package> <path to alembic.ini> <asgi app>
#
# `set -e` means a failed migration stops the container instead of
# serving requests against a half-migrated schema — the error shows up
# in `docker compose logs <service>` and the restart policy retries.
set -eu

PACKAGE="$1"
ALEMBIC_INI="$2"
APP="$3"

# --no-sync: the image's build stage already ran `uv sync --frozen` for
# this exact package, so the venv is already correct. Without this flag,
# `uv run` still performs its own implicit sync-check on every container
# start, which can reach out over the network (seen live: it hung
# indefinitely holding an open HTTPS connection to a package index
# mirror during a `docker compose up --build -d --force-recreate` cold
# start, with nothing wrong locally — confirmed via /proc on the stuck
# process). That's a needless runtime dependency on network access this
# step was never meant to have, and a flaky/firewalled network at
# deploy time would otherwise hang migrations forever with no sign of
# why in the logs (they'd just stop after this echo, mid-list).
echo "[$PACKAGE] applying database migrations..."
uv run --frozen --no-sync --package "$PACKAGE" alembic -c "$ALEMBIC_INI" upgrade head

echo "[$PACKAGE] starting API..."
exec uv run --frozen --no-sync --package "$PACKAGE" uvicorn "$APP" --host 0.0.0.0 --port 8000
