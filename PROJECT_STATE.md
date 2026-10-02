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
  access on everything, **except** `PUT /settings` (admin-only — see
  "Admin-only weekly goal" under frontend, below).
- ✅ Alembic baseline migration for the new tables, applied and verified
  with `alembic check`; `PointsEntry.task_id`/`todo_item_id` are
  `ON DELETE SET NULL` so deleting a task/todo keeps its points history.
- ✅ `GET /points/activity` — daily point totals (gap-filled with zero
  days), added to feed the Stats page's activity heatmap; `PointsEntry`
  gained a `task`/`todo_item` relationship and `PointsEntryOut` gained
  `task_name`/`todo_title` so the recent-activity feed can show a
  readable label instead of just an id (falls back to null if the
  source was since deleted).
- ✅ Points→EUR conversion: `HouseholdSettings.points_to_eur_rate`
  (nullable float, admin-only to set via `PUT /settings`), returned by
  `GET /settings` for display anywhere points are shown. Display/
  reference only, as specced — no payout process is connected.
- ✅ PDF reports: new `Report` table + `household_service/reports.py`
  (reportlab, pure-Python — no extra system packages in the container
  image) generates a by-week/by-month points table (plus an EUR column
  if a rate is set) and writes it to the `household-reports` Docker
  volume. `POST /reports` (admin, body `{period_type, period_date}` —
  any date within the target week/month), `GET /reports` (admin, list,
  newest first), `GET /reports/{id}/download` (admin, streams the PDF).
  Historical reports intentionally include a user's totals regardless
  of their *current* break status (`crud.leaderboard_for_period` —
  break mode affects the live leaderboard, not history).
- ✅ Web Push: `PushSubscription` table, VAPID keys in `.env`
  (`household/backend/scripts/generate_vapid_keys.py` generates a
  pair), `household_service/push.py` wraps `pywebpush` (runs the
  blocking send in a thread) and prunes subscriptions the push service
  reports as gone (404/410). Routes: `GET /push/vapid-public-key`,
  `POST /push/subscribe` / `/push/unsubscribe` (self), `POST
  /push/nudge` (admin-only — see below for why this is a button, not a
  schedule). Creating a todo with `assigned_to_id` set now pushes that
  person immediately (`crud.notify_todo_assigned`).
  - 🟡 **Weekly reminders are admin-triggered, not automatic.** The spec
    describes pushes "nudging users to log points during the week",
    which reads as a schedule — I deliberately built an admin button
    (`POST /push/nudge`: pushes everyone below the weekly goal, or
    everyone if no goal is set) instead of an automatic weekly cron/
    background task, to avoid the real failure modes that come with
    in-process scheduling in a single container (silent misses across
    restarts, idempotency bookkeeping, timezone assumptions) without a
    scheduling dependency. If true automatic scheduling is wanted,
    that's a deliberate follow-up, not an oversight.
- ⬜ Still not built: the auto-balancing assignment tool, and
  profile-picture upload for household users (storage's item-image
  pattern would carry over directly).

## Household service — frontend

- ✅ Built on the same vanilla HTML/CSS/JS conventions as
  `storage/frontend` — `css/tokens.css` is kept in lockstep (same
  black-and-white palette, dark theme, spacing/radius/shadow tokens),
  plus a new monochrome `--heat-0..4` scale for the activity heatmap so
  it stays within the b&w design rather than introducing a new hue.
  `js/auth.js`, `theme.js`, `toast.js`, `confirmDialog.js`, `main.js`
  are carried over unchanged; `api.js` is the same pattern minus the
  image-blob helpers (no photos in this domain).
- ✅ Six hash-routed pages: **Home** (your points this week + weekly
  goal progress, today's scheduled chores with one-tap complete, full
  task list with search/select-to-bulk-complete next to it, category
  filters), **Board** (the todo board — post/complete/cancel one-off
  requests, optionally directed at someone), **Stats** (leaderboard by
  all-time/this-week/**last week** (a closed, final range)/month, with
  the EUR-equivalent shown next to each total when an admin has set a
  rate; a GitHub-style activity heatmap — weekday labels fixed outside
  the horizontally-scrolling grid and all 7 shown, not GitHub's
  Mon/Wed/Fri — household-wide/just-me toggle, recent-activity feed),
  **Tasks** (category + task management: points, weekday/times-per-day
  schedule, ramp-up bonus config), **Settings** (break-mode toggle, a
  push-notification toggle, read-only weekly goal, theme, account,
  logout — reached via a topbar icon now, not the bottom nav),
  **Admin** (`#/admin`, admin-only: editable weekly points goal, EUR
  conversion rate, a "send weekly reminder now" button, and generate/
  list/download PDF reports; the natural home for the balancing-tool UI
  once that's built).
- ✅ Role gating mirrors storage's UX-only client-side pattern: viewers
  get every page read-only (no FABs, no select/complete/edit controls);
  the backend independently enforces the same rule. The weekly points
  goal goes one step further and is the one place this app actually
  distinguishes `admin` from `user` (both client-side — the Settings
  page only shows the Admin panel link to admins, and the router
  redirects a non-admin away from `#/admin` — **and** server-side —
  `PUT /settings` now requires the `admin` role, not just `can_write`).
- ✅ Bottom nav is 4 tabs (Home/Board/Stats/Tasks); Settings moved to a
  gear icon in the topbar so the bar doesn't get cramped on narrow
  screens. Admin has no nav entry of its own — reached only via the
  link on Settings (admins) or `#/admin` directly.
- ✅ Activity heatmap: weekday labels are a fixed column outside the
  horizontally-scrolling grid (previously they scrolled away with it —
  now they don't), and the grid opens pre-scrolled to the current day
  instead of the oldest one.
- ✅ Web Push: `sw.js` (push + notificationclick only — no offline
  caching, that's the separate unbuilt PWA-installability item) plus
  `js/push.js` (subscribe/unsubscribe, wraps the VAPID public key fetch
  and `PushManager`). Settings has a notification toggle per device;
  degrades to a plain "not supported" message in browsers without the
  Push API rather than erroring. `nginx.conf` serves `sw.js` as
  `no-cache` specifically (everything else is long-cached) so an
  updated service worker is picked up promptly.
- ✅ `docker-compose.yml` gained a `household-frontend` service (same
  shape as `storage-frontend`, behind the `household` profile);
  `household/frontend/README.md` covers the Caddy wiring and notes this
  is a **separate origin** from storage's frontend, so it needs adding
  as an extra Redirect URI on the same Authentik provider.
- ✅ Functionally tested end-to-end against the live stack with a
  jsdom-based harness (real DOM, real click events, real HTTP calls to
  the running auth/household containers) rather than just read —
  covered: today/all-tasks completion incl. ramp-up bonus, multi-select
  bulk complete, todo board complete, leaderboard + heatmap + recent
  feed rendering, task/category edit-modal round-trip, break-mode
  toggle, the admin-only weekly-goal flow (403 for `user`/200 for
  `admin` at the API, admin-page save round-trip, link/route visibility
  by role), the `#/admin` router redirect, and viewer-role control
  hiding on every page. No real browser was available in this
  environment to eyeball it visually — functionally verified, not
  visually (heatmap auto-scroll-to-today in particular: the code path
  is exercised, but jsdom has no real layout engine, so the actual
  visual scroll position is unverified).

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

1. Household backend follow-ups still not built: the auto-balancing
   assignment tool, and profile-picture upload. (PDF reports, EUR
   conversion, and Web Push all shipped this round — see above.)
2. Weekly Web Push reminders are admin-triggered (a button), not an
   automatic schedule — a deliberate simplification, not an oversight
   (see "Web Push" above for why). Worth a real decision later if
   automatic nudging turns out to matter.
3. Household frontend was built but only functionally tested (jsdom +
   real HTTP calls, no real browser available in that session) — worth
   an actual visual pass in a browser, especially the activity heatmap,
   Web Push permission prompt/toggle, and mobile layout at narrow
   widths.
4. Optional smaller gaps: "remove photo" on Storage items, PWA
   manifest/installability (Household — note Web Push's service worker
   is already in place; a manifest.json + icons would be the rest),
   clean URL routing (currently hash-based).
5. User's own action items: complete the Authentik-side GUI setup
   (provider, groups scope mapping, application, groups), add the
   household frontend's origin as an extra Redirect URI on that same
   provider, verify production Caddy routing for `/api/*` on each
   service (both frontends now need it), and set a real
   `VAPID_SUBJECT`/regenerate VAPID keys for production rather than the
   dev ones currently in `.env`.
6. Add Authentik admin panel for configuring the authentik connection(requires reauth before setting access)
7. Auto generate fallback admin credentials on deployment to avoid unsafe passwords or forgetting to setup a fallback user
