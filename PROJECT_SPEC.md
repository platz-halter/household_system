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
- Authentik groups map to roles — default names
  `household-system-admins`/`-users`/`-viewers`, but admin-editable
  (see "Admin tools" below), so an actual deployment's real group
  names (e.g. a homelab-wide `svc-` naming convention) don't need to
  match these literally.
- **Explicit allow-list**: an Authentik token belonging to none of the
  three configured groups is rejected outright, not let in as a
  viewer. A valid account on a shared Authentik instance that also
  serves unrelated homelab services is not, by itself, a reason to be
  let into this application at all.

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
  - **Settings**: theme selection, language selection (English/German,
    device-local — see CLAUDE.md's "Multi-language support" under the
    storage service), signed-in user info, logout.
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
- **Chained tasks**: a task can have one or more "chain tasks" attached
  — a specific occurrence of the parent (a board todo posted "from
  task," or an event group's own root) spawns one-off board todos for
  each of its chain tasks **at the same time it's created**, not only
  once the parent is actually completed (e.g. "Set the table" → "Clear
  the table" both land on the board together; "Fill the dishwasher" →
  "Clean non-dishwasher cutlery" too). Still tied to real occurrences of
  the parent, not an independent schedule of its own — a chain task has
  no weekly/monthly recurrence and is never sweep-assigned on a fixed
  calendar, so a day with only one or two real instances of "set the
  table" still only ever creates that many "clear the table" todos, not
  a fixed number regardless of how many times the parent really
  occurs — the timing just moved earlier, to the parent's creation
  instead of its completion.
  - Per chain task, the creator chooses **same person** or **another
    person**:
    - *Same person*: assigned directly to whoever the parent is
      currently assigned to right now (or left unassigned if the
      parent is) — never enters the balancing tool at all.
    - *Another person*: assigned immediately via the same fairness
      logic the balancing tool uses (currently-least-loaded eligible
      user), excluding whoever the parent is currently assigned to, if
      anyone. If nobody else is eligible, it's left open on the board.
  - Reassigning, claiming, or taking over the parent afterward never
    touches an already-spawned chain task — the two are only linked at
    the moment both are created, not kept in sync afterward.
  - Cancelling the parent deletes any of its still-open chain tasks
    along with it (a confirmation names them first) — they only existed
    because the parent was going to happen. A chain task someone's
    already completed, or already cancelled on its own, is left alone;
    only the still-open ones go.
  - Posting a todo "from task" on the board can deactivate this for
    that one todo specifically, when the picked task actually has a
    chain task to skip — the chain task is then never created for it,
    not even later if it's completed. Adding or removing which tasks
    chain a given task at all is only ever done from the Tasks page,
    never from the board.
  - A task can have multiple chain tasks, but chaining is capped at one
    level — a task that's already someone's chain task can't itself
    chain further tasks, and a task that's already chained can't be
    chained a second time to someone else. A task is a pure parent, a
    pure chain task, or neither — never both, which is what makes a
    chained loop structurally impossible to create in the first place.
  - A task that's a chain task (reachable only by being someone else's
    chain link) can't also be scheduled independently or completed
    directly without an explicit confirm — one source of instances per
    task by default, so the same occurrence can't accidentally earn
    points twice and the scheduler can't create duplicates of something
    only meant to exist as a chain reaction. Completing it directly
    anyway asks first, naming which task(s) chain it.
- **Event Groups**: a named bundle of tasks (e.g. "Dinner": "Set the
  table" and "Fill dishwasher") that posts all of them to the board at
  once, in one tap, instead of one at a time. Deliberately reuses
  chained tasks rather than inventing a second grouping mechanism — a
  group only needs to name its **root** tasks; a root's own chain tasks
  (e.g. "Fill dishwasher" → "Handwash non-dishwasher cutlery" and →
  "Empty dishwasher") are covered automatically, keeping the chaining
  system itself simple (a handful of chain links can cover a whole
  event) while still letting a group represent something bigger than
  its roots.
  - Creating or editing a group shows a live preview of every task it
    will cover right now — every root, plus each root's current chain
    tasks — before the group is saved, and again, re-checked fresh,
    right before it's actually triggered. Nothing is created without
    seeing the full list first.
  - The creator can deselect any individual chain task from counting as
    part of the group's own identity, even though it's still created as
    normal — e.g. "Empty dishwasher" still gets created alongside "Fill
    dishwasher" when the group triggers, it just isn't shown or
    clustered as part of "Dinner" specifically. A chain task not
    explicitly deselected is part of the group by default, including
    one chained in after the group was already created — the opt-out,
    not the task list itself, is what's remembered.
  - Triggering a group assigns its root tasks immediately via the same
    fairness logic the balancing tool uses, rather than waiting for its
    next scheduled sweep — an event like "hosting dinner" is happening
    now, not on the balancer's usual cadence. Can be triggered manually
    either from its own management screen or directly from the Board
    (an alternative to posting a single custom item), not just left to
    its schedule.
  - A task that's already someone else's chain task can't be a group's
    root — same "one source of instances" rule chain tasks already
    follow (see above); chain it from one of the group's own roots
    instead.
  - The board can cluster everything one trigger of a group created
    together into one clearly bounded card (e.g. "Dinner — Oct 6"), not
    just a heading above a flat list — with a toggle to turn that
    clustering off in favor of a flat list — either way, a task created
    through a group is still visibly tagged with which group it came
    from.
  - A group can also be scheduled to trigger itself — every day, or on
    specific weekdays, at a configured time — instead of needing
    someone to tap it every time. Triggering it by hand on a day its
    schedule would also fire doesn't produce a second batch; whichever
    happens first (manual or scheduled) is the one that counts for that
    day.
  - A whole triggered occurrence of a group can be bulk-deleted from
    the board in one action — e.g. you triggered "Dinner" by mistake,
    or it's not happening after all — with a warning naming exactly
    which tasks that removes before it happens. A task from that
    occurrence someone's already completed is kept, not deleted — it
    represents real work that already happened, regardless of what
    happens to the rest of the event.
- **Handing off an assigned task**: two ways, for two different
  situations.
  - *Takeover requests* (anyone): whoever currently holds a board todo
    or a recurring task assignment can ask a specific other eligible
    person to take it over — "I don't have time for this right now."
    Consent-based: the request sends a push notification, and nothing
    actually moves until the target accepts (or they can decline; the
    requester can cancel it first). Only one pending request per item
    at a time.
  - *Admin reassign* (admin-only): a direct, no-consent handoff of an
    open board item to someone else, for when a request-and-wait isn't
    the right tool (an admin just sorting out who's doing what). Still
    sends the new assignee a push notification — just an FYI, not a
    request to respond to.
  - Both exclude users on break from the picker, same as every other
    "assign this to someone" option in the app (see Break mode below).
- **Admin tools**:
  - A configurable week start (which weekday "this week" begins on) —
    applies everywhere points/goals are tracked by week: Home, Stats,
    the balancing tool, and weekly reports.
  - A configurable timezone, so the weekly reminder's schedule and an
    Event Group's own "trigger at" time mean what an admin actually
    typed — e.g. "18" means 18:00 in the household's own timezone, not
    UTC. Defaults to UTC, so an unconfigured household's existing
    schedules keep behaving exactly as before.
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
    authorize/token/end-session URLs, scope, **and which Authentik
    group name maps to which app role**) is editable here too, instead
    of hand-editing `.env` — and, for the group mapping specifically,
    instead of a source-code edit + rebuild — on the server. Saving
    requires a separate local-admin re-authentication (not just a
    currently-valid admin session) and takes effect across every
    service within about a minute, no restart needed — see
    `shared/auth.py` and `auth_service.main`'s `/authentik-config`
    routes.
  - An optional automatic cleanup for overdue board items: once a todo
    has been overdue for more than a configured number of days, it's
    permanently deleted on its own, so the board (and the "All" filter)
    doesn't keep accumulating stale clutter nobody's going to act on.
    Off by default. Never touches anything already completed, no
    matter how overdue it was before that.
- **Break mode**: a user can mark themselves on break (vacation,
  sickness), which excludes them from the leaderboard, from new task
  assignments (automatic or manual — the balancer, posting/editing a
  todo with an assignee, an admin reassign, or a takeover request
  target all refuse to hand them anything), and cancels any pending
  takeover request to or from them, until they turn it off. It only
  hides them from those things — it never touches points already
  earned: those keep counting toward their own personal stats and
  still show up in weekly/monthly PDF reports exactly as earned, break
  or not.
- **Installable to homescreen** (PWA-style — manifest + icons, not
  necessarily full offline support). Both frontends have this, not just
  Household — see the matching bullet under Storage above.

### Household planned pages

- **Home**: the signed-in user's own points, today's assigned tasks, a
  multi-select "complete tasks" action, task search, category filters.
- **Stats**: points leaderboard, recently completed tasks.
- **Admin panel**: generate/view reports, set the weekly points goal,
  set the default UI language for new accounts.
- **Task management panel**: categories (with icons; a task can belong
  to more than one), per-task point values, weekday/frequency scheduling
  per task, chain-task editing. A task's recurrence can also be
  **Manual** — no automatic occurrence of its own at all; it only ever
  exists when posted from the Board, chained from another task, or
  triggered as an Event Group root, which is the point: a task that's
  really only meaningful as one of those shouldn't also sit in
  everyone's ad-hoc daily list or get auto-swept by the balancer on top
  of whatever the group/chain already does. An admin can pin ANY task
  (any recurrence except a chain-child one) to always go to one
  specific person — a standing household agreement ("Alex always does
  the bathroom"), not a fairness choice. For a weekly/monthly task this
  opts it out of the auto-balancer's fairness pool entirely; for a
  daily or manual task, where the balancer never runs at all, it's an
  informational badge that still routes any todo actually created from
  that task to the pinned person. See CLAUDE.md's "Always-assign
  (pinned) tasks" and "Manual (non-repeating) tasks" for the full
  design. A calendar view (List/Calendar toggle)
  gives a month-at-a-glance of weekly tasks placed on their scheduled
  weekdays, with monthly tasks (which have no specific day of the
  month) called out separately — a quick overview of what's periodically
  scheduled without needing to read every task's own schedule text.
  Daily tasks show on every cell too, visually dimmed so a weekly
  task's specific day still stands out. Chain-child tasks are the only
  ones left off entirely — they have no schedule of their own to show
  (see Chained tasks above). Below it, an Event Groups
  section lists saved groups, each with an edit view (root tasks, live
  preview with per-chain-task opt-out, an optional auto-trigger
  schedule) and a one-tap manual trigger.
- **User settings**: break mode toggle, profile picture, UI language.

### Multi-language support

- English and German in both apps, but the two systems choose the
  language differently, matching each one's own data model:
  - **Household**: chosen per the household rather than hardcoded.
    Every signed-in user picks their own UI language from Settings
    (`HouseholdUser.preferred_language`); an admin sets which language a
    **brand new** account starts with (`HouseholdSettings.default_language`)
    — not retroactive, so changing the admin default never silently
    switches anyone already using the app. A notification's title/body
    renders in its RECIPIENT's own language; a PDF report renders in the
    household's shared default instead, since it's one document, not
    per-viewer.
  - **Storage**: has no per-service user table at all (see CLAUDE.md's
    "Storage has no admin/user distinction at all"), so the choice is
    purely device-local — a Settings page switcher, stored the same way
    the theme already is, with no admin default and nothing server-side
    to sync against.
- Deliberately out of scope: translating backend `ValueError`/
  `HTTPException` `detail` messages in either service (needs real error
  codes, a bigger change than a string lookup).

## Non-functional

- Deployment target is the existing homelab: Docker Compose, Caddy
  reverse proxy in front, Postgres as the datastore.
- Must stay usable by someone who isn't a primary web developer — this
  is why the frontend avoids a build step/framework, and why the CSS
  approach favors a small number of reusable primitives over a component
  library.
