#!/usr/bin/env bash
# Runs once, on first container start (docker-entrypoint-initdb.d convention).
# One Postgres instance, one database per service — keeps services
# independently droppable/backupable without needing separate containers.
set -euo pipefail

for db in auth household storage; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    SELECT 'CREATE DATABASE $db' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db')\gexec
EOSQL
done
