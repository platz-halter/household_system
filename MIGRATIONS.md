# Database migrations (Alembic)

Each backend service owns its own database (`auth`, `storage`, `household`)
and its own Alembic setup:

```
auth/alembic.ini                    auth/migrations/versions/
storage/backend/alembic.ini         storage/backend/migrations/versions/
household/backend/alembic.ini       household/backend/migrations/versions/
```

The shared environment logic lives in `shared/src/shared/migrations.py`;
each service's `migrations/env.py` is a few lines that import that
service's models and call it.

## How deployment works

Every backend container starts via `shared/entrypoint.sh`:

1. `alembic upgrade head` — applies any pending migrations
2. `uvicorn ...` — starts the API

If a migration fails the container exits **without** starting the API
(no serving against a half-migrated schema); the error is in
`docker compose logs <service>` and the restart policy retries.
Re-running `upgrade head` when nothing is pending does nothing, so
normal restarts are unaffected.

The app itself no longer creates tables on startup — **schema changes only
happen through migrations.**

## Existing installs (databases created before Alembic)

Nothing to do. The first migration of each service is a *baseline* that
creates a table only if it doesn't already exist. On your existing
databases it therefore just records "this database is at the baseline"
and touches no tables or data; on a brand-new database it creates the
full schema. Everything after the baseline is a normal strict migration.

## Making a schema change

1. Edit the models (`.../models.py`).
2. Make sure the database you generate against is up to date
   (`alembic upgrade head`, or just start the stack once).
3. Generate the migration **from your laptop** (so the new file lands in
   your working tree, not inside a container). This needs Postgres
   reachable on localhost: uncomment the `ports:` mapping on the
   `postgres` service in `docker-compose.yml`
   (`127.0.0.1:5432:5432`), then from the repo root:

   ```bash
   export DATABASE_URL="postgresql+asyncpg://hs_admin:<POSTGRES_PASSWORD>@localhost:5432/storage"
   uv run --package storage-backend alembic -c storage/backend/alembic.ini \
       revision --autogenerate -m "add barcode to items"
   ```

   Use `auth`/`household` and the matching `--package`/`-c` for the other
   services. If the password contains `@ : / # %`, URL-encode it.
   Alembic **refuses to run if `DATABASE_URL` is unset**, so you can't
   accidentally migrate the wrong database.
4. **Read the generated file** in `.../migrations/versions/` — autogenerate
   is a draft, not gospel (see gotchas below). Commit it.
5. Apply and verify:

   ```bash
   uv run --package storage-backend alembic -c storage/backend/alembic.ini upgrade head
   uv run --package storage-backend alembic -c storage/backend/alembic.ini check   # "No new upgrade operations detected"
   ```

`check` fails if the models and the migrations have drifted apart — worth
running before every commit that touches models.

## Handy commands

Run any of these with the same `DATABASE_URL` + `uv run --package … alembic -c …/alembic.ini` prefix as above:

| Command | What it does |
|---|---|
| `current` | which revision the database is at |
| `history` | list migrations |
| `upgrade head` | apply everything pending |
| `upgrade head --sql` | print the SQL instead of running it (review before prod) |
| `downgrade -1` | undo the last migration |
| `check` | fail if models ≠ migrations |

## Before deploying a migration to production

Take a backup first — schema changes on a database with real data are the
one thing here you can't just redeploy away:

```bash
docker compose exec postgres pg_dumpall -U hs_admin > backup-$(date +%F).sql
```

## Gotchas

- **Never edit a migration that has already been applied** anywhere (your
  server, a teammate's machine) — add a new one instead.
- **New `NOT NULL` column on a table with rows**: give it a
  `server_default` (or add it nullable, backfill, then tighten), otherwise
  the migration fails on existing data.
- **Renames**: autogenerate sees a rename as drop + add (data loss!). Edit
  the generated file to use `op.alter_column(..., new_column_name=...)` /
  `op.rename_table(...)`.
- **Postgres enums** (like `quantity_type`): adding a value needs
  `ALTER TYPE ... ADD VALUE`, and dropping a table doesn't drop its enum
  type — see the baseline's `downgrade()` for the pattern.
- The three services share one `Base` class but each process only imports
  its own models, so each service's autogenerate only ever sees its own
  tables.
