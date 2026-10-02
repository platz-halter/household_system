# Household System V2 — Project Spec

This is the design target: what the system is meant to do, independent of
how much is actually built. For what's actually implemented right now,
see `PROJECT_STATE.md`.

## Goals

- A self-hosted household management system covering two domains:
  item/storage tracking (cellar, pantry, etc.) and household chores with
  a points system.
- Low load: max 4–5 concurrent users.
- Easy to deploy and easy to maintain as a non-primary web developer —
  plain HTML/CSS/JS on the frontend (no build step), a CSS/design
  approach simple enough to extend without deep frontend expertise.
- Runs on the existing homelab: Docker Compose, behind the existing
  Caddy reverse proxy, authenticated through the existing Authentik
  instance.

## Architecture

- **Monorepo**, one uv workspace. Python backends on FastAPI.
- **One service per domain**, each independently deployable except the
  auth service, which is always required:
  - `auth` — local-account fallback login
  - `storage` — item/cellar tracking (backend + frontend)
  - `household` — chores/points (backend + frontend)
- **One Postgres container, one database per service** (not one DB per
  container) — simpler to run, but each service still owns its schema
  and data independently.
- **Docker Compose profiles** select which services run; `postgres` and
  `auth` have no profile (always on), `storage`/`household` are each
  behind their own profile.
- A `shared` workspace package holds code common to all services:
  settings, the DB session, and auth/token verification — defined once,
  not copy-pasted per service.
- Database schema is managed by **Alembic migrations**, one revision
  history per service. The app no longer creates tables on startup;
  each container runs `alembic upgrade head` before starting its API.

## Authentication & permissions

- **Authentik** is the primary authentication authority, via OIDC
  (Authorization Code + PKCE, public SPA client — no client secret).
- **Local accounts** are a genuine fallback, not an alternate mode:
  both local (HS256) and Authentik (RS256) tokens are verified on every
  request at all times, dispatched per-token by signing algorithm. This
  means local login keeps working if Authentik is unreachable, without
  redeploying or flipping an env var — and it's also how development
  continues without Authentik access.
- **Three roles**, same across every service: `admin`, `user`, `viewer`.
  - Viewers: read-only everywhere.
  - Users and Admins: normal full use.
  - (Nothing in the current spec distinguishes Admin from User beyond
    viewer-vs-not; if that's needed later — e.g. admin-only user
    management — it isn't designed yet.)
- Authentik groups map to roles: `household-system-admins`,
  `household-system-users`, `household-system-viewers`.
- An unrecognized or missing group/role fails closed to `viewer`.

## Storage System

Tracks physical items (cellar, pantry, etc.).

- **Item fields**: name, description, multiple aliases, quantity
  (countable with an integer, or uncountable with a free-text note like
  "half bag"), location (room / level / shelf), one photo.
- **Search**: free text across name, description, and aliases.
- **Filter**: by room/level/shelf and by quantity range.
- **Sort**: by name, quantity, or recency.
- **Pagination**.
- **Bulk operations**: bulk delete, and bulk edit (location and/or
  quantity, applied to a selected batch of items at once).
- **Permissions**: viewers read-only; users and admins can create, edit,
  delete, bulk-edit, bulk-delete, and upload photos.

### Storage frontend

- Clean black-and-white color scheme, with accent colors reserved for
  warnings/notifications (success/warning/danger/info).
- Responsive, mobile-first, usable cross-platform (not a native app —
  a well-behaved responsive web page).
- Theme system designed to support adding more themes later without
  restructuring (CSS custom properties, a small registry of theme IDs).
- **Pages**:
  - **General overview**: paginated item grid, search, filter, sort, a
    "maximize" image viewer for individual items, a button to add a new
    item, and a bulk-add flow ("save and add another" after submitting
    one item), plus multi-select for bulk edit/delete.
  - **Settings**: theme selection, signed-in user info, logout.
- Reachable both from home (via Caddy) and on the go (away from the home
  network, through the same Caddy/Netbird/Authentik chain already used
  for other homelab services).

## Household System (chores/points)

- **Points**: multiple users collect points for completing chores.
- **Reminders**: push notifications (native Web Push, not a third-party
  service) nudging users to log points during the week.
- **Scheduling**: tasks can be set up as a repeating weekly schedule
  (e.g. "dishwasher, 2x/day").
- **Balancing tool**: auto-assigns tasks, varies which user gets which
  task over time (avoids always assigning the same person the same
  task), and favors users currently sitting on fewer points.
- **Todo board**: users can post one-off tasks requesting completion
  within a set number of days (or "today"), and can request a specific
  other user take a task — which sends that user a push notification.
- **Ramp-up tasks**: a task can be configured to give a bonus if the
  same user always completes it alone (bonus amount configurable per
  task).
- **Admin tools**:
  - A points-to-money (EUR) conversion rate, for admins to track payout
    amounts. Display/reference only — no connection to an actual
    payment or payout process.
  - Downloadable PDF reports, by week or month. Past reports of the past months can also be downloaded.
- **Break mode**: a user can mark themselves on break (vacation,
  sickness), which excludes them from the leaderboard and from new task
  assignments until they turn it off.
- **Installable to homescreen** (PWA-style — manifest + icons, not
  necessarily full offline support).

### Household planned pages

- **Home**: the signed-in user's own points, today's assigned tasks, a
  multi-select "complete tasks" action, task search, category filters.
- **Stats**: points leaderboard, recently completed tasks.
- **Admin panel**: generate/view reports, set the weekly points goal.
- **Task management panel**: categories (with icons; a task can belong
  to more than one), per-task point values, weekday/frequency scheduling
  per task.
- **User settings**: break mode toggle, profile picture.

## Non-functional

- Deployment target is the existing homelab: Docker Compose, Caddy
  reverse proxy in front, Postgres as the datastore.
- Must stay usable by someone who isn't a primary web developer — this
  is why the frontend avoids a build step/framework, and why the CSS
  approach favors a small number of reusable primitives over a component
  library.
