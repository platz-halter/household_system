# Household System V2 — Project State

What's actually built and working right now, as of this writing. For what
the system is meant to become, see `PROJECT_SPEC.md`.

Status legend: ✅ done & tested · 🟡 partial/known gaps · ⬜ not started

## Dev environment & repo

- ✅ Arch Linux dev machine, Git repo, monorepo layout.
- ✅ `uv` workspace with a shared `shared` package plus `auth`, `storage`,
  `household` packages (backend halves).
- ✅ Docker Compose setup: one Postgres container (one DB per service),
  `postgres`/`auth` always on, `storage`/`household` behind their own
  compose profiles.
- ✅ Dockerfiles for all three backends, using a shared `entrypoint.sh`
  (`alembic upgrade head` → `uvicorn`).

## Shared package (`shared`)

- ✅ `config.py` — `Settings` (database_url, Authentik issuer/JWKS/client
  id, local JWT secret/algorithm, auth_service_url, cors_origins,
  environment) + `cors_origin_list()` helper. The old `auth_mode` toggle
  has been removed — no longer needed now that both auth paths are
  always active.
- ✅ `db.py` — async SQLAlchemy engine/session, declarative `Base`.
- ✅ `auth.py` — dual-mode token verification. Dispatches per-request by
  inspecting the JWT's signing algorithm header (`alg`): HS256 →
  local-account verification, RS256 → Authentik verification via JWKS.
  `GROUP_ROLE_MAP` maps Authentik groups to `admin`/`user`/`viewer`;
  unrecognized/missing groups fail closed to `viewer`. `require_role`
  dependency factory for route-level permission checks.
- ✅ `migrations.py` — shared Alembic `env.py` logic used by all three
  services, with a guard that raises clearly if `DATABASE_URL` is unset.

## Auth service

- ✅ Local account login (`/token`), bootstrap endpoint, user creation.
- ✅ `python-multipart` + `bcrypt<4.1` pin fixed (passlib 1.7.4
  incompatibility with bcrypt ≥4.1 was breaking password hashing).
- ✅ Alembic migrations added (previously this service had **no**
  migrations and no `create_all` either — a fresh deploy would have had
  zero tables; fixed as part of the Alembic rollout).
- ⬜ No user-management UI/API beyond what's needed for local-account
  bootstrap/login (e.g. no self-service password reset, no admin user
  list). Not currently in scope unless requested.

## Storage service — backend

- ✅ Item model: name, description, aliases (many, diffed on update
  rather than replace-all — fixes a prior unique-constraint violation
  bug), quantity (countable int or free-text uncountable note),
  location (room/level/shelf), one photo.
- ✅ Search (name/description/aliases), filter (room/level/shelf,
  quantity range), sort (name/quantity/recency), pagination.
- ✅ Bulk delete and bulk edit (location and/or quantity across a
  selected batch).
- ✅ `/locations` endpoint for filter UI.
- ✅ Authenticated image upload/serving.
- ✅ CORS via `cors_origin_list()`.
- ✅ Alembic migrations, baseline revision written as idempotent
  "create if not exists" so a pre-Alembic (`create_all`-created)
  database adopts cleanly without data loss.
- ✅ Role-gated writes: viewers read-only; users/admins full access.

## Storage service — frontend

- ✅ Vanilla HTML/CSS/JS, no build step, hash-based routing.
- ✅ Black-and-white theme with semantic accent colors
  (success/warning/danger/info); theme system built on CSS custom
  properties with a small registry so more themes can be added later.
- ✅ Responsive/mobile-first layout.
- ✅ Overview page: paginated item grid, search, filter, sort, image
  "maximize" viewer, add-item flow with bulk-add ("save and add
  another"), multi-select mode for bulk edit/delete.
- ✅ Settings page: theme selection, signed-in user info (subject, role,
  source), logout.
- ✅ Styled confirm-dialog modal (`confirmDialog.js`) replacing native
  `confirm()` popups everywhere (bulk delete, bulk edit, logout).
- ✅ Authenticated image loading via blob-URL pattern (`fetchImageUrl`/
  `invalidateImageUrl` in `api.js`), since `<img src>` can't carry an
  `Authorization` header.
- ✅ Authentik OIDC login integrated: Authorization Code + PKCE (S256,
  Web Crypto), "Log in with Authentik" as the primary action with a
  collapsible local-account form as fallback, silent refresh-token
  exchange on 401, Authentik end-session logout with `id_token_hint`.
- ✅ `getCurrentUserInfo()` helper resolves role/subject/source for both
  local and Authentik tokens — fixes an earlier bug where
  `canWrite()`/Settings read `decodeToken().role`, which is `undefined`
  for Authentik tokens (would have silently hidden the write UI from
  legitimate Authentik admins).
- 🟡 No "remove photo" control on an existing item (upload/replace only).
- ⬜ Still on hash-based routing (`#/...`); clean URLs were considered
  but not switched to.
- ⬜ No PWA manifest/installability for this service (not requested for
  Storage; it's in-scope for Household instead).

## Household service — backend

- ✅ Core chores/points domain built: `HouseholdUser` (auto-provisioned on
  first use from the JWT `subject` — this service doesn't own accounts),
  `Category`, `Task` (points, active flag, many-to-many categories,
  descriptive weekly schedule — `weekdays` 0–6 + `times_per_day` — and a
  configurable ramp-up bonus), `TodoItem` (one-off board requests with
  `due_in_days`, optional `assigned_to`), and a single `PointsEntry`
  ledger that both scheduled-task completions and completed todos write
  to (so the leaderboard/activity feed just sum/list one table).
- ✅ Routes: `/me` + `/users`, `/categories`, `/tasks` (+
  `/tasks/{id}/complete`, with ramp-up bonus logic), `/todos` (+
  `/complete`, `/cancel`), `/points/leaderboard` (excludes on-break users
  entirely, not just zeroed), `/points/recent`, `/settings` (singleton
  row, currently just `weekly_points_goal`).
- ✅ Role gating matches storage: viewers read-only, user/admin full
  access on everything (the spec doesn't yet distinguish admin from
  user beyond viewer-vs-not, so no feature here special-cases admin).
- ✅ Alembic baseline migration for the new tables, applied and verified
  with `alembic check`; `PointsEntry.task_id`/`todo_item_id` are
  `ON DELETE SET NULL` so deleting a task/todo keeps its points history.
- ⬜ Not built yet (deferred by explicit scope choice this round): the
  auto-balancing assignment tool, PDF report generation, the
  points↔EUR conversion admin setting, and Web Push notifications
  (todo items have an `assigned_to` field ready for it, but nothing
  sends a push yet). No profile-picture upload for household users
  either (storage's item-image pattern would carry over directly).
- ⬜ No household frontend yet — backend only so far.

## Database / migrations

- ✅ Alembic set up per service (independent revision histories), using
  the shared `shared/migrations.py` env logic.
- ✅ `shared/entrypoint.sh` runs `alembic upgrade head` before `uvicorn`
  in every container, for all three services.
- ✅ `MIGRATIONS.md` documents the day-to-day workflow and known gotchas
  (renames, NOT NULL additions, Postgres enum handling, pre-deploy
  backup via `pg_dumpall`).

## Authentication & permissions (cross-cutting)

- ✅ Both local (HS256) and Authentik (RS256) tokens verified at all
  times, dispatched per-token — not a global env-switched mode. Local
  login keeps working even if Authentik is unreachable.
- ✅ Three roles (`admin`/`user`/`viewer`) consistent across services;
  Authentik groups (`household-system-admins/-users/-viewers`) mapped
  to roles, failing closed to `viewer`.
- 🟡 User-side setup still pending on the user's end: creating the
  Authentik provider (public/PKCE client), the custom `groups` Scope
  Mapping, the `household-system` Application, and the three groups.
  Documented in `storage/frontend/README.md`, but this is a manual step
  on the user's Authentik instance, not something built in this repo.
- ⬜ No distinction yet between `admin` and `user` beyond
  viewer-vs-not (e.g. no admin-only user management). Not designed yet.

## Deployment / infra fixes already applied

- ✅ `docker compose --profile <name> up/down` usage corrected (the flag
  must precede the subcommand).
- ✅ Postgres init/healthcheck fixed to target the correct database
  name explicitly rather than a nonexistent default.
- ✅ Alpine/slim image healthchecks use Python's `urllib` instead of
  relying on `curl`, which isn't installed.
- ✅ `storage/backend/pyproject.toml` fixed to include a `[tool.uv.sources]`
  section that had been missing entirely.
- 🟡 Known constraint: a `POSTGRES_PASSWORD` containing `: / # @`
  breaks DSN parsing — documented as "use an alphanumeric password for
  now"; proper URL-encoding of special characters is a possible future
  fix but not implemented.
- 🟡 Local dev CORS/proxy routing: works when pointing `config.js`
  directly at exposed backend ports; production-correct routing of
  `/api/*` through Caddy to each backend is documented but depends on
  the user's own Caddy config outside this repo.

## Documentation

- ✅ `PROJECT_SPEC.md` — full design-decision summary (this session).
- ✅ `PROJECT_STATE.md` — this file.
- ✅ `MIGRATIONS.md` — Alembic workflow.
- ✅ `storage/frontend/README.md` — Authentik setup walkthrough + known
  gaps/notes.
- ✅ `.env.example` — reorganized (Auth / Authentik OIDC / Local
  fallback auth sections), `AUTH_MODE` removed as it no longer exists.

## Summary of what's next (not started, no action taken yet)

1. Household service: build its frontend (vanilla HTML/CSS/JS, same
   conventions as storage) against the backend that now exists —
   home/stats/admin/task-management/user-settings pages per
   `PROJECT_SPEC.md`.
2. Household backend follow-ups deferred this round: the auto-balancing
   assignment tool, PDF report generation, points↔EUR conversion
   setting, Web Push notifications, and profile-picture upload.
3. Optional smaller gaps: "remove photo" on Storage items, PWA
   manifest/installability (Household), clean URL routing (currently
   hash-based).
4. User's own action items: complete the Authentik-side GUI setup
   (provider, groups scope mapping, application, groups) and verify
   production Caddy routing for `/api/*` on each service.
5. Add Authentik admin panel for configuring the authentik connection(requires reauth before setting access)
6. Auto generate fallback admin credentials on deployment to avoid unsafe passwords or forgetting to setup a fallback user
