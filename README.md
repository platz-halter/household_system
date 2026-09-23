# Household System V2

## Layout

```
.
├── docker-compose.yml       # postgres + auth always on; household/storage via --profile
├── pyproject.toml           # uv workspace root
├── postgres/init/           # creates one DB per service on first boot
├── shared/                  # common config, DB session, and auth-token verification
├── auth/                    # local fallback login service (issues JWTs for local accounts)
├── household/
│   ├── backend/             # chores/points/tasks FastAPI service
│   └── frontend/            # not scaffolded yet
└── storage/
    ├── backend/             # cellar/item tracking FastAPI service
    └── frontend/            # not scaffolded yet
```

## Design decisions baked into this scaffold

- **One Postgres container, one database per service** (`auth`, `household`, `storage`) — easier to deploy than three DB containers, but each service still owns its own schema/data, so you can drop/back up one without touching the others.
- **`shared` is a uv workspace package**, not copy-pasted code — `config.py` (env-based settings), `db.py` (async SQLAlchemy session), and `auth.py` (token verification) live once and are imported by every service.
- **Auth verification is mode-switched, not duplicated**: `shared.auth.get_current_user` checks `AUTH_MODE` and either validates against Authentik's JWKS endpoint (normal operation) or a JWT signed by the local `auth` service (dev/fallback). Downstream services never branch on this themselves — they just call `Depends(require_role(...))`.
- **Compose profiles enforce "auth always required"**: `postgres` and `auth` have no `profiles` key (always start); `household-backend`/`storage-backend` are behind `household`/`storage` profiles.

## Running it

```bash
cp .env.example .env    # fill in POSTGRES_PASSWORD at minimum

# auth + postgres only
docker compose up --build

# everything
docker compose --profile household --profile storage up --build
```

Each service exposes `GET /health` and a `GET /me` smoke-test route that returns the caller's resolved role — hit that once Authentik is wired up (or `AUTH_MODE=local` + a seeded local user) to confirm the auth chain works end to end before building real features on top.

## Still open / next steps

- **Authentik application**: create the `household-system` OAuth2/OIDC application + provider in Authentik, and the `household-system-admins/-users/-viewers` groups referenced in `shared/src/shared/auth.py`'s `GROUP_ROLE_MAP` (adjust the names there to match whatever you actually create).
- **Migrations**: both backends currently call `Base.metadata.create_all` on startup for convenience. Swap to Alembic per-service before there's real data worth keeping.
- **Local user seeding**: nothing creates a local admin account yet — you'll want a one-off script or a `POST /users` admin route on the auth service.
- **Frontend**: intentionally untouched — decide on the CSS framework / build approach before scaffolding `household/frontend` and `storage/frontend`.
- **Web Push**: needs VAPID keys generated and a subscription-storage table (probably belongs in `household` and/or `storage`, wherever the triggering events live) — not started yet.
