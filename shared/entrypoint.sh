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

echo "[$PACKAGE] applying database migrations..."
uv run --package "$PACKAGE" alembic -c "$ALEMBIC_INI" upgrade head

echo "[$PACKAGE] starting API..."
exec uv run --package "$PACKAGE" uvicorn "$APP" --host 0.0.0.0 --port 8000
