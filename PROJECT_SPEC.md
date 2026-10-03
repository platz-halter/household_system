# Household System V2 — Project Spec

This is the design target: what the system is meant to do, independent of
how much is actually built. For what's actually implemented right now,
see `PROJECT_STATE.md`.

**As of version 1.0.0, every item in this document is implemented** —
see `PROJECT_STATE.md` for the verified, tested detail behind each one.
Treat this file as the design record going forward: a future feature
request gets added here first, then built.

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
  - In **Storage**, Admin/User are fully undistinguished — both have
    full read/write access everywhere. This is deliberate, not an
    unfinished gap: the household is a trusted group, and nothing in
    Storage's domain (editing items, locations, rooms) is sensitive
    enough to need gatekeeping beyond "logged-in member vs. read-only
    viewer." `admin` still exists as a role there only because the
    same three roles are shared across every service.
  - In **Household**, every "Admin tools" action below (weekly goal,
    money rate, reminder schedule, running the balancer on demand,
    generating/marking-paid reports, and the Authentik connection
    settings) is Admin-only; User is otherwise identical to Admin
    everywhere else in that app. Local-account user management (adding
    a user beyond the first bootstrap admin) is Admin-only too, but has
    no UI yet — API only (`auth`'s `POST /users`).
- Authentik groups map to roles: `household-system-admins`,
  `household-system-users`, `household-system-viewers`.
- An unrecognized or missing group/role fails closed to `viewer`.

## Storage System

Tracks physical items (cellar, pantry, etc.).

- **Item fields**: name, description, multiple aliases, quantity
  (countable with an integer, or uncountable with a free-text note like
  "half bag"), location (room / shelf / shelf level — "level" is a
  shelf's level, e.g. top/middle/bottom, not a building floor), one
  photo. Rooms are a managed list (add/delete on their own page), not
  free-typed per item, so the room filter/picker doesn't accumulate
  near-duplicate or typo'd values the way a free-text field would.
- **Search**: free text across name, description, and aliases.
- **Filter**: by room/shelf/level and by quantity range.
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
- **Installable to homescreen** (PWA-style — manifest + icons, not
  necessarily full offline support; no Web Push here, so no service
  worker either — see the matching bullet under Household below).

## Household System (chores/points)

- **Points**: multiple users collect points for completing chores.
- **Reminders**: push notifications (native Web Push, not a third-party
  service) nudging users to log points during the week.
- **Scheduling**: a task has a recurrence of `daily` (a standing chore,
  no auto-assignment — anyone logs it whenever), `weekly` (specific
  weekdays, e.g. "dishwasher, Mon/Wed/Fri, 2x/day"), or `monthly`.
- **Balancing tool**: two passes, run together.
  - *Sweep*: auto-assigns `weekly`/`monthly` tasks and any unclaimed
    Board todo to whoever's currently carrying the least load (points
    already earned this week, plus whatever they're already carrying
    into this run) — favoring users sitting on fewer points, rotating a
    task away from whoever last had it when another eligible person
    exists, and capping how many new items any one person can get in a
    single run so nobody's overwhelmed.
  - *Mid-week rebalance*: after the sweep, pulls an unfinished task away
    from whoever's pulled well ahead and hands it to whoever's still
    meaningfully behind, so one person getting a head start early in the
    week doesn't just sit uncorrected until the next sweep. Only moves a
    task nobody's made any progress on yet, never one with the weekly
    goal already on the line (it won't newly cause the person losing it
    to miss their goal if they weren't going to already), and a given
    task can only be pulled once per period, so it can't bounce back and
    forth.
  - A ramp-up task (see below) is exempt from both rotation and
    pulling — it stays with its current solo completer, since moving it
    would permanently kill the bonus for everyone.
  - Runs automatically once a day (not just at the start of a period —
    the rebalance pass needs regular rechecking to actually catch
    someone falling behind mid-week), or on demand from the Admin panel.
    A user going on break releases whatever they haven't finished yet,
    so it can be picked back up instead of staying stuck.
- **Todo board**: users can post one-off tasks requesting completion
  within a set number of days (or "today"), and can request a specific
  other user take a task — which sends that user a push notification.
  An unclaimed, unrequested todo can also be self-claimed by anyone, or
  picked up by the balancing tool above.
- **Ramp-up tasks**: a task can be configured to give a bonus if the
  same user always completes it alone (bonus amount configurable per
  task).
- **Admin tools**:
  - A configurable week start (which weekday "this week" begins on) —
    applies everywhere points/goals are tracked by week: Home, Stats,
    the balancing tool, and weekly reports.
  - A points-to-money (EUR) conversion rate, for admins to track payout
    amounts. Display/reference only — no connection to an actual
    payment or payout process.
  - Downloadable PDF reports, by week or month. Past reports of the past
    months can also be downloaded. Can auto-generate the past week's
    report as soon as each week ends, in addition to generating one for
    any period on demand; either way, a push notification goes to
    admins when a new report is ready. The admin panel's reports list
    flags whichever one covers last week, and each report can be marked
    paid (reference only, same as the conversion rate above — no real
    payout is connected) to track which have actually been settled.
  - The Authentik connection itself (issuer, JWKS URL, client ID,
    authorize/token/end-session URLs, scope) is editable here too,
    instead of hand-editing `.env` on the server. Saving requires a
    separate local-admin re-authentication (not just a currently-valid
    admin session) and takes effect across every service within about
    a minute, no restart needed — see `shared/auth.py` and
    `auth_service.main`'s `/authentik-config` routes.
- **Break mode**: a user can mark themselves on break (vacation,
  sickness), which excludes them from the leaderboard and from new task
  assignments until they turn it off. It only hides them from those two
  things — it never touches points already earned: those keep counting
  toward their own personal stats and still show up in weekly/monthly
  PDF reports exactly as earned, break or not.
- **Installable to homescreen** (PWA-style — manifest + icons, not
  necessarily full offline support). Both frontends have this, not just
  Household — see the matching bullet under Storage above.

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
