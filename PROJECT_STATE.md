# Household System V2 — Project State

**Version 1.1.0** — a new feature on top of 1.0.4's four patch releases
(which sit on top of 1.0.0, the first declared release: every
`PROJECT_SPEC.md` item implemented, production hardening and a full
pre-deploy security pass done — see this file's own entries below).
- 1.1.0 adds **chained tasks**: completing one task can auto-spawn
  others onto the board as one-off todos, so a parent chore like "Set
  the table" can define child chores like "Clear the table" that only
  ever need to happen when the parent actually did, instead of being
  separately scheduled (and over-scheduled) by the balancer on their
  own cadence. See its own entry under "Household service — backend"
  for the full design (same-person-direct vs. different-person-via-
  balancer semantics, multi-level chains, cycle rejection, the "one
  source of instances" exclusion from the sweep/direct-completion/
  Home's standalone list) and "Household service — frontend" for the
  Tasks-page chain-link editor and the "After: {parent}" todo label.
- 1.1.0 also adds (same uncommitted release — nothing from this version
  has shipped yet, so these three ride along rather than bumping to
  1.2.0): on-break users are now excluded from every "assign this to
  someone" picker and are rejected server-side if assigned anyway
  (previously only the balancer itself respected break mode); an
  **admin-only reassign** for open board todos (`POST /todos/{id}
  /reassign`, no acceptance needed — distinct from a takeover request);
  and **takeover requests** — anyone holding a board todo or a
  recurring task assignment can ask a specific other eligible person to
  take it over, consent-based (push-notified, accept/decline/cancel).
  See "Household service — backend"/"— frontend" for the full design
  and the live-verification notes.
- 1.1.0 also picked up three rounds of user-reported follow-ups, still
  the same uncommitted release: viewers are now excluded from the
  balancer/chain-task auto-assigner (not just on-break users); the
  reassign vs. takeover-request icons/wording were confusing and the
  Board couldn't send a takeover request at all (both fixed); a real
  bug where picking a chain task and pressing the main Save button
  silently didn't chain it (fixed by making the pick itself the save,
  no separate step to forget); the chain-task picker is now
  mobile-friendly (search + category filter instead of a flooded native
  `<select>`); a notification inbox (bell icon next to Settings) where
  a takeover request can be accepted or declined directly, without
  navigating to Home; and completing a chain-child task directly now
  shows a confirm dialog naming which task(s) chain it, instead of a
  flat unexplained 409, with an explicit override to proceed anyway.
  See "Household service — backend"/"— frontend" for each one's own
  entry.
- 1.0.1 made the Authentik group→role mapping admin-editable (see its
  own entry under "Auth service"), on top of 1.0.0's Authentik
  connection panel.
- 1.0.2 excludes viewers from the Household points leaderboard (see its
  own entry under "Household service — backend") — found while
  investigating the issue that led to 1.0.3, reported directly by the
  user once the actual bug was found.
- 1.0.3 fixes a real bug 1.0.1 introduced: both frontends' `js/auth.js`
  kept a hardcoded mirror of the group→role mapping, so a group renamed
  through the new 1.0.1 admin panel left that admin stuck on `viewer`
  *client-side* — including blocked from `/admin` by the router's own
  guard — even though the backend was already authorizing them
  correctly the whole time (confirmed live: the same bearer token got a
  200 from an admin-only route called directly, while the same page's
  own UI showed "viewer"). See its own entry under "Household service —
  frontend" / `shared/auth.py`'s entry for the full trace — diagnosed by
  decoding the actual production token in the browser console down to
  "the group is right there in `groups`, the config matches it exactly,
  so the bug can't be in the mapping at all."
- 1.0.4 is a deliberate **access-control policy change**, not a bug fix:
  Authentik tokens belonging to none of the three configured groups are
  now rejected outright (401) instead of defaulting to `viewer`. Asked
  for directly, in plain terms: "In a true single trust architecture
  nobody that isn't explicitly given access should receive access."
  Prompted by the SAME production investigation as 1.0.2/1.0.3 — the
  user's real Authentik instance serves several other homelab services
  (`svc-omada-admins`, `svc-proxmox-admins`, `svc-netbird-admins` all
  showed up in their decoded token alongside the household-system
  groups), so under the old fail-closed-to-viewer design, anyone with a
  valid account on that shared instance — not just actual household
  members — could log into this app and get read access, as long as
  Authentik itself didn't separately restrict who could reach this
  Application's login flow. See `shared/auth.py`'s entry for the
  implementation and live verification.

`shared/src/shared/__init__.py`'s `__version__` is
the single source of truth, surfaced in every service's `GET /health`
and OpenAPI `info.version`, and in both frontends' Settings page footer
(`js/version.js`) — all five `pyproject.toml` files' `version` fields
are kept in sync with it by hand (no publish step reads them, so
there's nothing to automate the sync with).

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
  Authentik groups map to `admin`/`user`/`viewer` via the admin-editable
  `admin_group`/`user_group`/`viewer_group` config (no more hardcoded
  `GROUP_ROLE_MAP` — see 1.0.1's and 1.0.4's own entries below for that
  history); a token matching none of the three is rejected outright
  (401), not downgraded to `viewer` (see 1.0.4's own entry — this used
  to fail closed to viewer, changed once a real multi-service Authentik
  instance made the gap concrete). `require_role` dependency factory
  for route-level permission checks.
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
- ✅ **Authentik admin panel** (PROJECT_SPEC.md "Admin tools" /
  `PROJECT_STATE.md`'s own former "what's next" item 6): an admin can
  now change the Authentik connection (issuer, JWKS URL, client ID,
  authorize/token/end-session URLs, scope) through Household's Admin
  page instead of hand-editing `.env` on the server **and** both
  frontends' `config.js` — the previous reality, called out as a real
  pain point in `storage/frontend/README.md`'s own setup steps.
  - New singleton-row table `authentik_settings` in the `auth` database
    (same pattern as household's `HouseholdSettings`). `GET
    /authentik-config` is deliberately **public** (no auth) — these
    seven values were already shipped to every browser via the old
    `config.js`, and are equally discoverable from Authentik's own
    `.well-known` document, so there's nothing to protect by hiding
    them — and returns the saved row, or the static `.env`-sourced
    defaults (now all seven fields, previously only
    issuer/jwks_url/client_id — see `shared/config.py`) if nothing's
    been saved yet, so a fresh deploy with no admin-panel use still
    works exactly as before.
  - `shared/auth.py` gained `_AuthentikConfigCache` (60s TTL, polls
    `{auth_service_url}/authentik-config` — the previously-unused
    `AUTH_SERVICE_URL` setting finally has a real purpose) so every
    service's own independent JWKS-based token verification picks up a
    saved change within about a minute, with **no restart** — falling
    back to the last-known-good config, then to the static env
    defaults, if the auth service is ever unreachable, so a transient
    blip there can't take down Authentik verification everywhere else.
    `_JWKSCache` is now **keyed by jwks_url** rather than a single
    global slot, specifically so a changed JWKS URL takes effect
    immediately instead of still trusting keys fetched from the OLD
    url for up to its own 300s TTL. Also fixed, found while touching
    this code: the JWKS fetch had no error handling at all before —
    an unreachable Authentik would have 500'd; now a clean 503.
  - **The actual security design — this was the load-bearing part, not
    a UI nice-to-have.** `PUT /authentik-config` requires BOTH
    `require_role("admin")` (a currently-valid admin bearer token, same
    as every other admin route) AND a **separate re-authentication
    check**: the request body carries a local admin's username and
    password, verified with the same `verify_password` the `/token`
    login route uses. This is deliberate and was the user's own
    explicit requirement for this feature (PROJECT_STATE.md's
    pre-session backlog literally said "requires reauth before setting
    access"), not a precaution added for its own sake: whoever can
    repoint `issuer`/`jwks_url` at a JWKS they control can mint tokens
    every service in the system would accept as an admin — access that
    would outlive the bearer token used to call this endpoint and
    survive a password change on whatever account that token belonged
    to. A currently-valid admin session (Authentik OR local) is
    therefore NOT sufficient on its own to change this; the caller must
    separately know a local admin's actual password, which also means
    the panel keeps working even when Authentik itself is what's
    broken — exactly when it's needed. `POST /authentik-config/reset`
    (deletes the override row, reverting to the `.env` defaults) has
    the identical reauth requirement, same risk class in the other
    direction.
  - **Save-time validation** (`_validate_issuer`): before writing
    anything, fetches `<issuer>/.well-known/openid-configuration` and
    checks its own `issuer` field matches, then fetches `jwks_uri` and
    checks it actually returns signing keys — rejects (400) otherwise.
    Catches a typo'd URL before it locks every admin out of Authentik
    login, rather than discovering it on the next real login attempt.
    Explicit 5s timeouts throughout (this session's own `uv run`
    hang-on-unreachable-network incident, elsewhere in this file, is
    exactly the failure mode explicit timeouts prevent).
  - **Frontend**: both frontends' `config.js` no longer hardcode
    `AUTHENTIK_CLIENT_ID`/`AUTHORIZE_URL`/`TOKEN_URL`/`END_SESSION_URL`/
    `SCOPE` (only the client-computed `AUTHENTIK_REDIRECT_URI` remains,
    since that one genuinely can't come from the backend — it has to be
    wherever the page itself is being served from). `js/auth.js` (kept
    byte-identical between both frontends, the established convention)
    fetches `GET {AUTH_BASE}/authentik-config` instead, cached
    in-module per page load, and used by `loginWithAuthentik`/
    `handleAuthentikCallback`/`tryRefreshAuthentikToken`. Two traps
    caught before shipping: (1) `boot()`'s `handleAuthentikCallback()`
    must stay network-free on an ordinary page load — the config fetch
    only happens *after* the existing `if (!code && !error) return
    false` early-out, so the common case (no `?code=`) never waits on
    it, same reasoning as this session's earlier Authentik-timeout fix.
    (2) `logout()`'s Authentik end-session redirect needs
    `end_session_url` but must not need a fetch (it has to work
    instantly, including when the auth service is down) — fixed by
    stashing `end_session_url` in `localStorage` at login time
    (alongside the existing `id_token`), so logout only ever reads a
    value it already has.
  - **A real, pre-existing bug this surfaced**: storage frontend's
    `config.js` had `AUTHENTIK_CLIENT_ID: ""` — empty — meaning
    Authentik login through the storage frontend specifically was
    already broken before this change (household's copy had the
    correct value). Centralizing on the backend's `.env`-sourced value
    fixes this as a side effect for both frontends at once; also fixed
    the backend-side version of the same drift — `.env`'s
    `AUTHENTIK_AUTHORIZE_URL`/`TOKEN_URL`/`END_SESSION_URL` were still
    the unfilled `authentik.example.com` placeholders from
    `.env.example` (dead until this change, since nothing backend-side
    ever read them before), while the real working values only ever
    lived in `config.js` — corrected `.env` to the real
    `pressnet.duckdns.org` values before switching anything over to
    read from it, specifically so this change wouldn't break the live
    deployment's actual login flow.
  - **Admin UI**: a new "Authentik connection" section on Household's
    `/admin` page — seven plain text fields, a local-admin
    username/password sub-form for the reauth check, Save and "Reset to
    .env defaults" buttons (the latter behind a confirm dialog, since
    it signs out every Authentik session). A 403 from this specific
    save (wrong reauth password) needed its own handling — `api.js`
    normally turns ANY 403 into a generic "you don't have permission"
    toast, which would be actively misleading here (the caller already
    has the admin role; the reauth password is what's wrong) — `api.js`
    gained an optional `{silent: true}` 3rd argument to `put`/`post` so
    this one save can show the real backend-provided detail message
    instead.
  - **Verified end-to-end against the live stack, not just by code
    review**: generated a throwaway RSA keypair, served a real
    `jwks.json` + `.well-known/openid-configuration` from an ephemeral
    container on the `hs-internal` network (reusing the already-built
    `auth` image's `python -m http.server`, no image pulled), and
    saved that fake issuer through the actual `PUT /authentik-config`
    route with correct reauth (a temporary local admin created via
    `POST /users` for this purpose, deleted afterward via direct SQL —
    no `DELETE /users` route exists, same precedent as other
    SQL-cleanup fixtures this session). Minted an RS256 token signed by
    the fake key with `groups: ["household-system-admins"]`: **both**
    `storage-backend` and `household-backend` — neither of which was
    restarted — accepted it as a real admin within seconds, proving the
    cross-service propagation genuinely works without a restart. Reset
    to defaults via the real reset route; after the config cache's 60s
    TTL elapsed, the same fake token was rejected by both services
    again (503 specifically, because this sandbox has no real route to
    the actual `authentik.pressnet.duckdns.org` to re-fetch its real
    JWKS — confirmed that domain is genuinely unreachable from here —
    but the fake-issued admin access was conclusively revoked either
    way, which is what the test was actually checking). Also confirmed
    the reauth gate itself: a `PUT` with a valid admin bearer token but
    a wrong reauth password 403s with "Re-authentication failed" and
    saves nothing; a `PUT` with no bearer token at all 401s before
    reauth is even checked. **Could not test against the real
    Authentik instance** — it isn't reachable from this environment —
    so the actual production login flow (real Authentik, real browser
    OIDC redirect) is unverified; only the dynamic-config-propagation
    and reauth-gating mechanics were proven, against a fake IdP
    standing in for a real one.
  - New Alembic migration for the `authentik_settings` table, reviewed
    (plain `CREATE TABLE`, no backfill needed since it's a brand-new
    always-fully-specified singleton row), `alembic check` and a
    fresh-DB upgrade both verified clean.
- ✅ **Pre-deployment security pass** (full XSS/SQL-injection/route-auth/
  file-upload/JWT-verification audit across every service, requested
  explicitly before the first real deploy). Came back clean except for
  two real findings, both addressed:
  - `shared/config.py`'s `Settings` gained a `model_validator` that
    refuses to start (raises on `Settings()` construction) when
    `ENVIRONMENT=prod` and `LOCAL_JWT_SECRET` is either of its two
    known-insecure placeholder values (this class's own default
    `"dev-only-change-me"`, or `.env.example`'s
    `"changeme-generate-a-real-secret"`) or under 16 characters —
    without this, a deploy that forgot to set a real secret would
    silently run with a value anyone who's seen this repo already
    knows, letting them forge a local-account JWT for any
    subject/role, admin included. Gated on `ENVIRONMENT=prod`
    specifically (not always-on) so local dev doesn't need a
    throwaway secret generated just to run the app — `environment`
    already exists for exactly this kind of "relax a check for local
    dev" distinction (see `shared/db.py`'s SQL-echo toggle). Verified
    all three cases live: placeholder+prod raises with a clear message,
    a real secret+prod starts clean, placeholder+dev still works.
  - **`POST /token` had no rate limiting at all** — new
    `auth_service/rate_limit.py`, a small in-memory lockout (5 failed
    attempts / 15 minutes, 429 + `Retry-After` past that) keyed on the
    *username being attempted*, not client IP. IP-keying was considered
    and rejected: requests reach this service through two reverse-proxy
    hops (external Caddy, then this container's own nginx), and
    getting the real client IP right through both isn't guaranteed to
    be configured correctly in every deployment; keying on the account
    actually being targeted matches the real threat (repeated password
    guessing against one account) regardless of proxy setup. Checked
    *before* touching the DB/password, so a locked-out account can't
    keep being guessed against; only failed attempts count (a
    legitimate user logging in repeatedly is never penalized,
    `record_success` clears the counter); a nonexistent username is
    rate-limited identically to a real one, so there's no
    username-enumeration oracle via differing lockout behavior. Bounded
    to `MAX_TRACKED_USERNAMES = 10_000` distinct usernames (oldest
    evicted past that) so spraying many fake usernames at the endpoint
    can't exhaust memory — this project's actual scale (a handful of
    real accounts) never comes close. A single uvicorn worker per
    service (see `shared/entrypoint.sh`) means this in-memory state is
    authoritative for the whole process; no shared store like Redis
    needed at this scale. Verified live: 5 failed attempts against a
    bogus username pass through as 401, the 6th 429s with a correct
    `Retry-After`, and a *different* username is unaffected by another
    username's lockout.
  - **Noted, intentionally not changed**: `.env`'s current
    `LOCAL_JWT_SECRET`/`BOOTSTRAP_ADMIN_PASSWORD` share the same value
    — flagged, but the user confirmed this `.env` is dev/test-only and
    the real deployment will be a fresh machine with its own generated
    secrets, so no rotation was needed here.
  - **Accepted, lower-priority residual risk, left as-is**: the
    Authentik panel's `_validate_issuer` fetches whatever `.well-known`
    URL an admin submits — a mild SSRF primitive, but only reachable by
    an already-authenticated, already-reauth'd admin who has much
    stronger primitives available through that same endpoint anyway,
    so it doesn't meaningfully raise their actual privilege.
  - Everything else checked came back clean: no raw SQL anywhere in any
    service (confirmed via `grep` for string-built queries — ORM-only
    throughout); every route across all three backends has an explicit
    `CurrentUser` auth dependency except the intentionally-public ones
    (health checks, `/token`, `/bootstrap-admin`, the public
    `/authentik-config` GET — verified programmatically, not by eye);
    `shared/auth.py`'s HS256/RS256 dispatch is safe against
    algorithm-confusion attacks (the token's own claimed `alg` only
    selects which verifier function runs, never which key it trusts —
    each branch pins its own fixed algorithm/key pair); both image/
    photo upload routes (`storage`'s item images, `household`'s
    avatars) validate content-type against an allowlist that excludes
    `image/svg+xml` (the classic image-upload stored-XSS vector) and,
    more importantly, generate the stored filename server-side from
    that validated type plus a random UUID — never from the uploaded
    file's own name — which also makes path traversal structurally
    impossible on every file-serving route checked (item images,
    avatars, PDF reports); and a full sweep of every `innerHTML`
    assignment across both frontends for unescaped user data turned up
    nothing — `toast.js` uses `.textContent` (immune by construction),
    `confirmDialog.js`/`openModalShell` escape their whole message/
    title internally so every caller is safe by default even when the
    caller itself doesn't escape, and every other list-rendering
    template (items, tasks, categories, todos, rooms, reports) escapes
    each interpolated field individually at its actual render site.
- ✅ **Authentik group → role mapping is now admin-editable**, extending
  the Authentik connection panel rather than adding a new one — asked
  for directly after walking through the previous answer (edit
  `shared/src/shared/auth.py`'s `GROUP_ROLE_MAP` + both frontends'
  `ROLE_FROM_GROUPS`, rebuild every backend and the storage frontend,
  redeploy) and finding that friction worth removing the same way the
  issuer/JWKS/client-id fields already were.
  - `authentik_settings` gained three columns, `admin_group`/
    `user_group`/`viewer_group` (new migration, `server_default`
    matching the previous hardcoded names, `alembic check` and a
    fresh-DB upgrade both verified clean). `shared/config.py` gained
    matching `authentik_admin_group`/`_user_group`/`_viewer_group` env
    fallbacks (same default values). `GET`/`PUT`/`POST
    /authentik-config/reset` all extended to carry the three fields —
    same reauth requirement as the rest of that endpoint, same risk
    class (whoever controls the group mapping controls who's an admin,
    same as whoever controls the JWKS source).
  - **`shared/auth.py`'s `GROUP_ROLE_MAP` module-level dict is gone.**
    `_role_from_groups(groups, config)` now takes the live config
    (already fetched once per call by its only caller,
    `_verify_authentik_token`) and checks the three group names in a
    fixed admin > user > viewer precedence — simpler and more
    predictable than the old dict-based version, which effectively
    kept the token's own group *array order* as the ad-hoc tiebreak
    whenever someone belonged to more than one recognised group (an
    accident of the old implementation, not a designed behavior worth
    preserving). Relies on the three names being distinct, which...
  - **...`PUT /authentik-config` now enforces**: rejects (400) a blank
    group name, or reusing one name across two roles. Caught during
    design, before writing any save logic: reusing a name doesn't mean
    "grant both roles" the way it might sound — the fixed precedence
    check means only the first-checked role (admin) would ever
    actually be reachable through that name, silently stranding the
    other role's access. Simpler to reject outright than to document
    an edge case nobody actually wants.
  - **Verified end-to-end against the live stack**, same fake-IdP
    methodology as the original panel (fresh throwaway RSA keypair +
    ephemeral `python -m http.server` container on `hs-internal`, no
    image pulled): saved a config with `admin_group` renamed to
    `custom-renamed-admins` through the real `PUT` route with correct
    reauth; a token minted with `groups: ["custom-renamed-admins"]`
    was accepted as admin by `household-backend` (`GET /reports`, a
    real admin-only route, 200) within seconds, no restart; the exact
    same claim but with the **old** default group name
    (`household-system-admins`) was correctly rejected (403, fell back
    to `viewer`) — proving the rename actually took effect rather than
    just adding to the old mapping. Also confirmed the duplicate-name
    rejection live (`admin_group == viewer_group` → 400) and reset back
    to `.env` defaults afterward. Temporary local admin (for reauth)
    and the fake IdP container both cleaned up afterward, same
    precedent as the original panel's test.
  - **Originally shipped as deliberately out of scope — turned out to
    be wrong, fixed in 1.0.3.** The reasoning at the time: both
    frontends' `ROLE_FROM_GROUPS` (`js/auth.js`) staying a hardcoded
    mirror seemed like a UI-display-only tradeoff, not a real risk,
    since the backend independently enforces the real rule. What that
    missed: `getCurrentUserInfo()` isn't just a display label — the
    router's `/admin` route guard calls it too, so a stale mirror
    doesn't just show the wrong badge, it actively blocks a real admin
    from ever reaching the Admin panel client-side, even though the
    backend would authorize every request they could still make
    directly. This bit a real production deployment the very first
    time a group got renamed through the panel. See 1.0.3's entry
    under "Household service — frontend" for the actual fix
    (`warmGroupRoleMap()`, same dynamic config the backend uses,
    fire-and-forgotten at boot so an unreachable auth service still
    can't delay the first render).
- ✅ **1.0.4: Authentik access is now an explicit allow-list, not
  fail-closed-to-viewer.** `_role_from_groups` returns `Role | None`
  instead of always returning a `Role` — `None` means the token's
  `groups` claim matched none of the three configured group names, and
  `_verify_authentik_token` now raises `401` ("Not a member of any
  group recognized by this application") in that case, rather than
  constructing a `CurrentUser` with `role="viewer"`. A validly-signed
  token from the right issuer/audience is no longer, by itself, enough
  to get in — it also has to actually belong to this application's
  user base. Local-account tokens are untouched (they never involved
  group matching — an admin creates them with an explicit role already
  assigned via `POST /users`, which was always an allow-list of one).
  - **The actual motivating scenario, concretely**: the same real
    production token from 1.0.3's investigation carried groups like
    `svc-omada-admins`/`svc-proxmox-admins`/`svc-netbird-admins` —
    other homelab services on the same shared Authentik instance. Under
    the old design, an account in only those groups (no household-system
    group at all) would still have been let into this app as a viewer.
    Whether that's actually exploitable end-to-end also depends on
    whether Authentik's own Application-level access policy restricts
    who can reach this app's login flow at all — orthogonal to this
    app's own code, and the user's own Authentik configuration, not
    verified from here — but this app no longer silently waves through
    an unrelated account on the backend's own say-so either way, which
    is the only part of that question this codebase can actually
    control.
  - **Verified live** with the same fake-IdP methodology as every other
    Authentik-adjacent change this project: minted two tokens against a
    throwaway signed IdP — one with a recognized group
    (`svc-household-system-admins`, confirmed still works, 200 from an
    admin-only route, no regression) and one with *only* unrelated
    groups (`svc-omada-admins`, `svc-proxmox-admins`, `mgmt-users` —
    deliberately mirroring the real token's actual other-service
    groups) — confirmed the second one now gets a clean `401` with the
    new detail message, checked independently against **both**
    `household-backend` and `storage-backend` (each verifies Authentik
    tokens on its own, so both needed checking separately). Temporary
    local admin and fake IdP container cleaned up afterward, config
    reset to `.env` defaults.
  - **Frontend left as-is, deliberately, disclosed rather than silently
    decided**: an Authentik user who's now rejected still completes the
    OIDC exchange from the browser's point of view (Authentik itself
    issues them a token; this app's role check only happens once that
    token hits the backend), so the frontend stores a session and
    attempts to render before its first API call 401s — at which point
    the *existing* `api.js` 401 handler (already built for session
    expiry) clears the token and bounces them to `/login`. Functionally
    correct and secure — the rejection is real and already verified
    above — but the user-visible moment is a brief flash of the app
    before being kicked back out, not an immediate "you don't have
    access to this application" message at the point of login. Fixable
    (decode the token client-side right after the exchange, before
    ever calling `setSession`) but intentionally not built without
    being asked, since it's pure UX polish on top of an already-enforced
    rule, not a security gap.

## Storage service — backend

- ✅ Item model: name, description, aliases (many, diffed on update
  rather than replace-all — fixes a prior unique-constraint violation
  bug), quantity (countable int or free-text uncountable note),
  location (room/shelf/shelf-level), one photo.
- ✅ Search (name/description/aliases), filter (room/level/shelf,
  quantity range), sort (name/quantity/recency), pagination — verified
  end-to-end against 46 real seeded items (20/20/6 across 3 pages, no
  duplicates/gaps, correct prev/next disabled states at both ends,
  negative-offset/over-200-limit query params correctly rejected as 422).
- ✅ Bulk delete and bulk edit (location and/or quantity across a
  selected batch).
- ✅ **Rooms are now a managed entity**, not free-typed: a new `Room`
  table (`rooms`) is the single source of truth; `Location.room_id` is a
  hard FK to it (migration backfills `rooms` from every distinct
  pre-existing `locations.room` value, then converts the column to the
  FK — verified all 3 of the pre-existing test rooms preserved). `level`
  is now documented/treated as a shelf level, not a building floor.
  `GET/POST /rooms`, `DELETE /rooms/{id}` (blocked with 409 while any
  *item* — not just a leftover unused Location row — still sits in that
  room; deleting an unused room also sweeps its now-orphaned Location
  rows, since they'd otherwise block the delete on a dangling FK).
  Creating/editing an item with an unknown room name now 400s instead of
  silently creating it.
- ✅ `/locations` endpoint for level/shelf filter dropdowns (still
  derived from locations actually in use); room dropdowns (filter panel
  + item form) now come from `/rooms` instead.
- ✅ Authenticated image upload/serving.
- ✅ CORS via `cors_origin_list()`.
- ✅ Alembic migrations, baseline revision written as idempotent
  "create if not exists" so a pre-Alembic (`create_all`-created)
  database adopts cleanly without data loss.
- ✅ Role-gated writes: viewers read-only; users/admins full access.
- 🐛 Fixed: `create_item`/`update_item`/the image-upload route only
  refreshed `item.location` after a write, not the nested
  `item.location.room` — reading `location.room.name` during response
  serialization (now needed since the Room migration) then triggered an
  async-incompatible lazy load and crashed with `MissingGreenlet`.
  Consolidated into one `crud.reload_item()` used by all three call
  sites; a stray commit-then-crash from this (the commit succeeds before
  the serialization step did) left one orphaned test item behind, since
  cleaned up.

## Storage service — frontend

- ✅ Vanilla HTML/CSS/JS, no build step, clean path-based routing (see
  its own entry below for the switch away from hash-based routing).
- ✅ Black-and-white theme with semantic accent colors
  (success/warning/danger/info); theme system built on CSS custom
  properties with a small registry so more themes can be added later.
- ✅ Responsive/mobile-first layout.
- ✅ Overview page: paginated item grid, search, filter, sort, image
  "maximize" viewer, add-item flow with bulk-add ("save and add
  another"), multi-select mode for bulk edit/delete.
- 🐛 Fixed a real glitch testers hit: selecting an item in bulk-select
  mode called `refreshItems()` — a full re-fetch from the server plus a
  from-scratch rebuild of every card (skeleton flash, every thumbnail
  resetting to the placeholder icon and reloading) — on every single
  tap. Selecting a card now only toggles that one card's class/badge in
  place and re-renders the bulk bar; no fetch, no rebuild. Verified via
  a fetch-call counter in tests: 0 network calls on select/deselect.
  Also removed a duplicate, dead/conflicting second copy of the
  `.item-card`/`.bulk-bar`/`.select-badge` CSS block (the live JS never
  used `.select-badge`; the duplicate `.bulk-bar` silently overrode the
  floating-rounded positioning with a conflicting edge-to-edge one).
- 🐛 Same glitch also hit entering/exiting bulk-select mode itself (the
  checklist toggle button and "cancel selection") — both still called
  `refreshItems()`. Fixed by caching the last-fetched page's items and
  splitting `refreshItems()` (fetch + render) from a new `renderGrid()`
  (render only, from the cache); the toggle and cancel buttons now call
  `renderGrid()`, so switching selection mode makes no network call and
  shows no skeleton flash.
- ✅ Filter panel "Shelf level" is now a number input instead of a
  dropdown (native numeric keypad on mobile, consistent with the
  quantity min/max fields) instead of a `<select>` built from distinct
  known level values.
- ✅ Filter panel field order: room+quantity, then shelf+"shelf level"
  (previously room+level, then shelf+quantity) — level now visually
  groups with shelf, matching its "shelf level, not building floor"
  meaning. Add/edit item dialog: room is now a `<select>` sourced from
  the managed rooms list (see backend) instead of free text, and the
  shelf field now comes before the (renamed) "Shelf level" field.
- ✅ New Rooms page (`/rooms`, linked from Settings → Storage →
  "Manage rooms"): add a room, or delete one (blocked with a toast if
  it's still in use) — the only way rooms get created now; the item
  form's room dropdown won't let you free-type a new one.
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
- 🐛 Fixed a real hang: the code-exchange (`handleAuthentikCallback`) and
  silent-refresh (`tryRefreshAuthentikToken`) fetches to
  `AUTHENTIK_TOKEN_URL` had no timeout, so if Authentik was unreachable
  (down, DNS/network issue) the `await` just hung forever — in
  `handleAuthentikCallback`'s case, blocking `main.js`'s `boot()` before
  `startRouter()` ever runs, which looks like the whole app is stuck in
  an infinite loading loop with no recovery but a hard refresh. Both now
  go through a shared `fetchWithTimeout()` (`auth.js`, 8s, `AbortController`)
  so an unreachable Authentik is treated as an ordinary failed
  login/refresh instead — same file in both `storage/frontend` and
  `household/frontend` (kept byte-identical; see their own note above).
- ✅ `getCurrentUserInfo()` helper resolves role/subject/source for both
  local and Authentik tokens — fixes an earlier bug where
  `canWrite()`/Settings read `decodeToken().role`, which is `undefined`
  for Authentik tokens (would have silently hidden the write UI from
  legitimate Authentik admins).
- 🟡 No "remove photo" control on an existing item (upload/replace only).
- ✅ **Mobile-friendly picker dialog for Shelf** (same motivation/pattern
  as household's task picker — see its own entry under Household
  frontend): Shelf is free text accumulated from items' locations, not a
  managed list like Room, so it has no inherent size cap and can grow
  into a long, unsearchable `<select>` on mobile as a real inventory
  fills in. The filter panel's Shelf field is now a button that opens a
  popup (`openShelfPickerModal` in `overview.js`, built on the existing
  `openModalShell` helper already used by the item dialogs) with a
  search box and a scrollable list, "Any" pinned first; picking a row
  sets the filter and closes the popup. Still narrowed by Room first,
  same as before (picking a room resets Shelf and the picker only
  offers that room's shelves). Room itself stays a native `<select>` —
  it's deliberately a small, curated managed list (see the Rooms page
  below), not the problem this solves. Verified with a mocked jsdom
  pass: the old `<select>` is gone, the picker lists the right shelves
  for the current room filter (or all of them with no room picked),
  search narrows the list, picking a row updates the label and closes
  the popup, and changing Room re-narrows a subsequently-opened picker
  to the new room's shelves.
- 🐛 Fixed loading skeletons flashing on fast (typical, local-network)
  responses — they rendered immediately, so a request resolving in
  50ms still showed one for a single frame, which read as a glitch
  rather than a loading state. A small `showSkeletonAfterDelay(root,
  html, delayMs = 200)` helper (defined locally per file, same
  convention as this frontend's `escapeHtml`) starts a timer instead of
  rendering immediately; call the function it returns as soon as the
  request settles. A response faster than the delay cancels the timer
  before it ever fires, so no skeleton renders at all; a genuinely slow
  one still gets one, just not from the first instant. Applied to both
  of this frontend's skeleton call sites — the item grid (`refreshItems`)
  and the Rooms page list. Verified with a mocked jsdom pass (both the
  helper in isolation and a real page): a fast response never shows the
  skeleton at any point; a deliberately slow one still does, and clears
  correctly once the real content arrives.
- ✅ **Switched from hash-based to clean path-based routing**
  (`/overview`, `/settings`, `/rooms`, `/login` — no more `#/`).
  `router.js` reads/writes `window.location.pathname` via
  `history.pushState`/`replaceState` instead of `location.hash`,
  listens for `popstate` instead of `hashchange`, and adds a
  document-level click interceptor that turns a click on an internal
  `<a href="/...">` into client-side navigation (no full page
  reload) — the standard no-framework SPA pattern. The interceptor is
  deliberately narrow: same-origin only, path must be one of this
  app's known routes, and it explicitly skips a `target`-carrying or
  `download`-attributed anchor (needed because of the next point).
  **Traps caught before shipping**: (1) both `index.html` files loaded
  `css/...`/`js/main.js` as *relative* paths — harmless under hash
  routing, since the document URL was always `/`, but a direct load of
  a deep route like `/rooms` would have resolved those to
  `/rooms/js/main.js` and 404'd, blanking the page; fixed by making
  every asset reference root-absolute (`/css/...`, `/js/main.js`), and
  the same fix applied to `push.js`'s `navigator.serviceWorker.register("sw.js")`
  → `"/sw.js"`. (2) A naive click interceptor keying only on same-origin
  would have hijacked clicks on the admin panel's synthetic PDF-download
  `<a>` (`admin.js`'s `downloadReport`, a `blob:` URL with `download` set
  — same origin as the page) and any `/api/...` link, since `config.js`
  now points those at the same origin too; fixed by requiring the
  clicked path to be a *known route* and excluding `download`/`target`
  anchors outright. (3) The post-login redirect in `main.js`'s `boot()`
  uses `history.replaceState` directly, not the router's own
  `navigate()` — calling `navigate()` there would render once itself and
  then render again when `startRouter()`'s own initial route check runs
  right after, since the click/popstate listeners (and this app's only
  render trigger) don't exist yet at that point in boot. (4) `api.js`'s
  401 handler and `auth.js`'s local-account `logout()` branch deliberately
  do a hard `window.location.assign("/login")` / the existing `_navigate`
  test-indirection, NOT an import of `router.js`'s `navigate()` — both
  are low-level modules nearly every page imports, so importing the
  router back into them would create a router → page → api/auth → router
  cycle; a hard reload also guarantees stale module-level state doesn't
  survive a forced logout. `login.js` (itself one of the pages `router.js`
  imports) *does* import `navigate()` for the post-success redirect —
  safe here since it's only called from inside an event handler, never at
  module-evaluation time.
  nginx needed **no changes** for this — the SPA fallback
  (`try_files $uri $uri/ /index.html;`) added earlier this session
  already serves `index.html` for any unmatched path, which is exactly
  what a clean-URL deep link/refresh needs. Did add `^~` to all four
  `/api/*` proxy `location` blocks while in the area: without it, nginx
  would let a *regex* location (the JS/CSS/image cache-control blocks)
  win over the `/api/*` prefix match if an API path ever happened to end
  in one of those extensions — not currently true for any real route
  (`/items/{id}/image`, `/me/photo` etc. have no extension), but one
  route away from a request silently 404ing as a "static file" instead
  of reaching the backend, so fixed defensively rather than after the
  fact.
  Verified: curled every route on both ports directly (`/`, each real
  route, and a bogus path) and confirmed each returns `index.html` with
  `id="app"` present; confirmed the old relative-asset bug would have
  404'd (`/rooms/js/main.js` does, now that nothing requests it);
  confirmed a query string survives the `rewrite`+variable `proxy_pass`
  indirection (`?limit=999` still hit the backend's own `le=200` 422,
  not a 404 or a silently-truncated query); confirmed the `^~` change
  didn't break the auth/storage/household API proxies. No real browser
  available, so the click-interceptor/`popstate`/history mechanics were
  verified with a mocked jsdom harness instead (built and run directly
  against both frontends' real, unmodified `router.js`): boots directly
  into a deep route without bouncing to `/login`, a nav-link click
  updates `location.pathname` and calls `preventDefault` with no
  `jsdom` "Not implemented: navigation" error (proving the interceptor,
  not a real browser navigation, handled it), `history.back()` restores
  the previous path and re-renders, and a `{replace: true}` navigate
  doesn't grow `history.length`.
- ✅ **Installable to homescreen** — originally scoped to Household only
  in `PROJECT_SPEC.md`, extended to Storage on request. Same
  `manifest.json` shape as Household's (`name`/`short_name`,
  `start_url: "/overview"`, `display: "standalone"`, theme colors
  matching the shared `tokens.css` default), plus a parallel `icons/`
  directory. Different art from Household's checkmark, for the two
  apps to stay visually distinguishable on a homescreen: a solid
  three-face isometric box/package glyph (white top face, two gray
  side faces, thin dark seams) rather than a wireframe copy of the
  existing thin-stroke `box` UI icon, same "bold shape over literal
  line-icon copy" reasoning as Household's checkmark — a multi-line
  wireframe box would turn to mush at home-screen icon sizes the same
  way a 2px-stroke checklist glyph would have. 192/512/maskable-512/
  apple-touch variants, `index.html` gained the matching `<link
  rel="manifest">`/`apple-touch-icon`/`apple-mobile-web-app-*` tags,
  `Dockerfile` copies `manifest.json` + `icons/` into the image.
  **No service worker added** — unlike Household, Storage has no Web
  Push feature to justify one, and a service worker is no longer a
  hard requirement for Chrome's installability criteria (only the
  manifest + HTTPS/localhost); adding an empty no-op one just to tick
  an outdated checklist item would be pure cargo-culting. `nginx.conf`
  needed no changes, same reasoning as Household (`.json`/`.png` are
  both already handled by existing rules). Verified the same way:
  rebuilt the container, curled the manifest and all four icons (200,
  correct content-types/dimensions), and loaded the real page in
  headless Chromium at phone width for an actual screenshot.

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
- ✅ Points→money conversion: `HouseholdSettings.points_to_money_rate`
  (nullable float) + `currency` (ISO 4217 code, e.g. "EUR"/"USD",
  defaults to "EUR" — renamed from the original EUR-only
  `points_to_eur_rate` once currency became selectable), both
  admin-only to set via `PUT /settings`, returned by `GET /settings`
  for display anywhere points are shown. Frontend formats amounts with
  `Intl`/`toLocaleString({style:"currency", currency})`, which handles
  any valid code's symbol automatically — no manual symbol map needed
  client-side. Display/reference only, as specced — no payout process
  is connected.
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
  Designed rather than bare: letterhead header, summary stat callouts
  (total points/participants/top performer/**money per point**/total
  value — the rate itself is shown, not just the totals it produces), a
  styled leaderboard table with a per-row proportional share bar, a
  per-user converted-amount column, and a green highlight on #1, and a
  page-numbered footer — all in the app's black-and-white palette plus
  the one semantic accent (success green). Reportlab has no `Intl`, so
  the PDF renders money as `amount CURRENCY` (e.g. "35.40 USD") rather
  than a locale-specific symbol — unambiguous and font-safe regardless
  of which of the Admin panel's currencies is selected.
- ✅ Web Push: `PushSubscription` table, VAPID keys in `.env`
  (`household/backend/scripts/generate_vapid_keys.py` generates a
  pair), `household_service/push.py` wraps `pywebpush` (runs the
  blocking send in a thread) and prunes subscriptions the push service
  reports as gone (404/410). Routes: `GET /push/vapid-public-key`,
  `POST /push/subscribe` / `/push/unsubscribe` (self), `POST
  /push/nudge` (admin-only manual "send now"). Creating a todo with
  `assigned_to_id` set now pushes that person immediately
  (`crud.notify_todo_assigned`).
- ✅ **Real scheduling**, via `household_service/scheduler.py`
  (APScheduler's `AsyncIOScheduler`, wired into FastAPI's lifespan in
  `main.py` — started/shut down alongside the app). Built as the
  general-purpose piece future time-based features should register a
  job with, not a one-off for the nudge. The weekly reminder is now a
  real automatic schedule, superseding the earlier manual-only design
  (see git history if curious): an hourly tick
  (`crud.run_scheduled_nudge_if_due`) checks `HouseholdSettings.
  nudge_weekday`/`nudge_hour` (admin-configurable in the Admin panel,
  off by default) against the current time, and `last_nudge_sent_week`
  for idempotency (so a restart mid-hour, or the manual button firing
  in the same week, can't double-send). Job *definitions* are
  re-registered from code on every startup (in-memory jobstore); only
  the *effect* that must not double-fire is persisted, in the database.
- ✅ **Auto-balancing assignment tool** (PROJECT_SPEC.md), in two passes,
  both run by `crud.run_balancing` every time it's invoked. `Task` gained
  a `recurrence` column (`daily`/`weekly`/`monthly`; the old "only on
  specific weekdays" checkbox is now this 3-way picker in the Tasks
  page) and a new `TaskAssignment` table (task, user, period_start/end,
  `reassigned_at`; unique per task+period) records who holds a
  `weekly`/`monthly` task for its current week/month — a `daily` task is
  never a candidate, it stays a standing chore anyone logs any day.
  There's no separate "completed" flag: `crud._remaining_points` derives
  how much of a task's whole-period value is still outstanding by
  counting actual `PointsEntry` rows against its expected instance count
  (`weekdays × times_per_day` for weekly, `times_per_day` for monthly) —
  a completion by *anyone*, not just the holder, counts down what's left,
  so someone pitching in on another person's task is correctly reflected
  rather than double-counted as still-outstanding load.
  - `household_service/balancing.py` holds both passes as **pure
    functions** (no DB session — see its own docstring and
    `household/backend/tests/test_balancing.py`, 22 unit tests). Pass 1,
    `balance()`: candidates are every active `weekly`/`monthly` task
    without an assignment yet this period, plus every open, unclaimed
    Board todo sitting unclaimed longer than `CLAIM_WINDOW` (6h — gives a
    person first crack at claiming it before the balancer does). Each
    item is weighted by its expected points over the whole period, and
    heaviest items are placed first, each going to whoever's currently
    least loaded (points already earned this week, plus whatever they're
    already carrying into this run) — which is exactly the same ranking
    as "furthest from the weekly goal," so the goal value itself doesn't
    need to enter the comparison. A non-ramp-up task skips its last 1-2
    assignees when another eligible candidate exists (rotation); a
    ramp-up task instead stays sticky with its one current completer, as
    long as they're still eligible, since reassigning it would
    permanently kill the bonus for everyone (see `crud.complete_task`'s
    ramp-up logic). A count-based cap (`ceil(total_candidates /
    eligible_users) + 1`, counting what someone's already carrying in)
    stops any one person being handed a long string of items even when
    point values are skewed; anything left over stays unassigned (todos
    stay claimable; tasks wait for the next run).
  - Pass 2, `rebalance()` — **the mid-week fairness check**: after the
    sweep, re-reads everyone's load and pulls an unfinished task from
    whoever's most ahead to whoever's still meaningfully behind, so
    someone pulling ahead early in the week doesn't just sit uncorrected
    until the next period's sweep. A task is only a pull candidate if
    nobody's logged *any* progress on it yet (`has_progress`), it isn't
    ramp-up-enabled, it wasn't assigned today (`assigned_today` — gives
    the original holder at least a day), and it hasn't already been
    pulled once this period (`reassigned_at IS NULL` — each assignment
    can only move once per period, the guard against it bouncing back
    and forth as small day-to-day point swings flip who looks "ahead").
    A move only happens if `load[holder] − load[recipient]` is strictly
    greater than the item's own point value — enough to guarantee the
    move narrows the gap without just flipping who's ahead, with no
    separate tunable threshold to get wrong. A donor guard also blocks a
    pull that would newly drop an on-track holder below the weekly goal
    (if they were already going to miss it regardless, fairness wins
    instead). Shares the same per-run cap as pass 1, so a recipient who
    already hit it via the sweep can't also be a pull target.
  - `crud.run_balancing` gathers everyone's current load, runs the
    sweep, recomputes load, runs the rebalance pass, persists both, and
    sends one combined summary push per affected user (not one per
    item) — e.g. "2 new items (+8 pts); 1 task moved to you to even out
    the week." Always stamps `HouseholdSettings.last_balance_run` to
    today (same idempotency pattern as `last_nudge_sent_week`), so a
    manual Admin-panel run and the automatic schedule can't double-run
    the same day. `scheduler.py`'s hourly `_balancing_tick` now runs this
    **once a day** (previously Monday/1st-of-month only) — the mid-week
    pass needs regular rechecking to actually catch someone falling
    behind, not just at the start of a period; a stray bug in the
    nearby `_weekly_nudge_tick` (unpacking a 3-tuple into 2 names, so it
    raised every time the nudge actually fired) was fixed in the same
    pass.
  - Going on break (`PATCH /me` with `on_break: true`) releases whatever
    that user hasn't finished yet (now using the same remaining-points
    check, so partial progress is respected): any `TaskAssignment` with
    real work still outstanding is deleted, and any open Board todo
    still assigned to them is unassigned — so the next run (or another
    person) can pick it back up instead of it staying stuck.
  - Routes: `GET /assignments` (current week's + month's assignments,
    everyone can read), `POST /balancing/run` (admin-only; optional
    `?as_of=` date query param for testing/override — now returns
    `reassignments` too, each a task + from-user + to-user + points
    moved), `POST /todos/{id}/claim` (self-assigns an open, unclaimed
    board item via a conditional `UPDATE … WHERE status='open' AND
    assigned_to_id IS NULL`, not a read-then-write, so two people
    claiming the same item at once can't both win it — the loser gets a
    409). Admin panel's "Run balancer now" result now has a "Mid-week
    rebalancing" section listing each move (task, from → to, points),
    and each per-user row shows net points including both new work and
    reassignments.
  - Verified against the live `household-backend` with real HTTP calls
    (minted local JWTs, since the real admin password wasn't available
    this session): the sweep assigns weekly/monthly tasks and skips
    daily ones; a holder boosted 100 points ahead via a separate
    completed todo had their untouched weekly assignment (backdated by a
    day via SQL, to clear the `assigned_today` guard) pulled and handed
    to the least-loaded of two other eligible users, with the push/API
    summaries reporting the correct from/to/points; a third run of the
    same day left that same assignment alone (one-pull-per-period
    confirmed); `last_balance_run` stamped correctly (in UTC — a
    same-named local-date assertion in my own test script was the only
    thing that didn't match, not the backend). All test fixtures (tasks,
    todos, users, points entries, the settings stamp) were cleaned up
    afterward. Noticed, but did not touch, that the real pre-existing
    "Test" todo had since been cancelled and assigned to the real admin
    account between sessions — not something any of my test calls did,
    so left as-is rather than reverting what looks like genuine use.
- 🐛 Fixed a real gap: completing a task from Home never checked whether
  it had already been done enough times today, so a `times_per_day: 1`
  task never actually left the "Today" list — tapping Complete
  repeatedly just kept awarding points with no limit, and (as a side
  effect) could inflate the balancing tool's "how much of this task is
  still outstanding this period" count past what really happened.
  `crud.complete_task` now rejects (409) a completion past the task's
  own `times_per_day` for the current calendar day, counting completions
  by anyone, not just the caller — same "shared responsibility" logic as
  `_remaining_points`. New `GET /tasks/completions-today` (admin-ordered
  before `/tasks/{task_id}` in `main.py`, same `/items/bulk*`-style
  routing gotcha as storage) returns each task's count for today, so the
  frontend can show the same state the backend will enforce before the
  user even taps. Home now fetches it alongside everything else: a task
  disappears from "Today" once it hits its daily count, and shows a
  "Done today" badge with no Complete button in the full task list
  (both lists re-render after any completion — single-tap or bulk — not
  just the one it happened in, since the other list's state can change
  too). Verified live: a 1x/day task 409s on a second same-day
  completion, a 2x/day task allows exactly two and 409s a third, and
  `GET /tasks/completions-today` reports the right count; a mocked jsdom
  pass confirmed the Today-removal, the badge/button swap in the full
  list, and that completing a task's last instance for the day updates
  both lists together. Test fixtures cleaned up afterward (left an
  unrelated, clearly real completion count on the pre-existing
  `TestTask` alone, rather than deleting someone's actual point
  history).
- 🐛 Fixed another real gap: Home's "Assigned to you" and "Today"
  sections only ever read recurring `TaskAssignment` rows — an assigned
  Board todo (via "Request from" when posting it, the Claim button, or
  the balancer sweeping an unclaimed one) never showed up on Home at
  all, only on the Board page itself. Home now also fetches `GET
  /todos?status=open&assigned_to_id=<your id>` (no backend changes
  needed, that filter already existed) alongside the assignments call.
  "Assigned to you" shows every open todo assigned to you, any due date
  or none, labeled "From the board" to distinguish it from a recurring
  task; "Today" additionally surfaces just the due-today-or-overdue ones
  (same urgency tones the Board page's own due badge already uses) —
  a todo due later, or with no due date, stays out of Today the same way
  a weekly task not scheduled for today does. Each gets a one-tap
  Complete button (`POST /todos/{id}/complete`, same endpoint Board
  uses), and completing it from Home refreshes both sections immediately
  (not just the one it was tapped from, since the todo disappears from
  both at once). Verified live (claimed a todo, confirmed the exact
  endpoint/filter Home now calls returns it) and with a mocked jsdom
  pass covering all four due-date cases (overdue, due today, due later,
  no due date) plus the post-completion refresh; test fixtures cleaned
  up afterward.
- 🐛 Fixed a timezone bug in `util.js`'s `dueBadge()`: it compared a
  todo's `due_date` against the viewer's LOCAL calendar date, but the
  backend always writes that date from `datetime.now(UTC).date()`
  (`crud._todo_due_date`). For any viewer not in UTC, there's a stretch
  of every day where the local calendar date has already rolled past
  midnight but UTC's hasn't (or the reverse) — a todo due "today" by the
  backend's clock could show as "Overdue" the moment it was created,
  purely from that mismatch, not any real lateness. Both sides are now
  anchored to UTC, matching how the date was actually written. Proved
  the fix with a before/after repro (forced the clock to a late-UTC
  instant under `TZ=Pacific/Kiritimati`, +14h — enough to push the local
  calendar day past UTC's): the old code showed "Overdue", the new one
  "Due today", for the exact same `due_date`; existing "yesterday"/
  "tomorrow" cases were re-verified unaffected. This is the single
  shared `dueBadge` both Home and Board render through, so the fix
  applies everywhere a due-date badge shows up.
  - Noted but not changed (same root cause, lower visibility so far):
    `todayWeekday()`/`startOfWeekIso()` in the same file have the
    identical local-vs-UTC gap, and feed Home's "Today" weekday-match
    filter and the "points this week" leaderboard window — worth the
    same UTC-anchoring treatment if a user near this kind of day
    boundary reports a task appearing on the wrong day or points landing
    in the wrong week.
- 🐛 Removed Home's "Today" section entirely — it duplicated entries
  already shown one scroll down in the full task list (and, after the
  board-sync fix above, in "Assigned to you" too), with no behavior of
  its own beyond that filtered view. Took `loadToday()`, the now-unused
  `todayWeekday` import, and the Today-specific branches of
  `afterTaskCompletion`/`afterTodoCompletion` with it;
  `completionsTodayCache`/`doneForToday()`/the "Done today" badge stay,
  since those still drive the full task list's own complete-button
  state.
- ✅ **Mobile-friendly picker dialogs**: a native `<select>` populated
  from an open-ended backend list (tasks, specifically) turns into a
  long, unsearchable scroll on a phone once there are more than a
  handful of options — fine on desktop (type-ahead jumps to an option),
  not on mobile. Board's "New todo" modal's "From task" field is now a
  button that opens a full popup (`openTaskPickerModal` in `board.js`,
  stacked on top of the New-todo modal — same nested-overlay pattern
  `confirmDialog.js` already uses elsewhere): a search box, a category
  chip row (reusing the same categories the Tasks page manages) to
  filter by, and a scrollable list of tap targets with a "Custom
  (one-off)" option always pinned first. Selecting a row prefills the
  same three fields the old `<select>`'s change handler did and closes
  the picker; the parent modal's button updates to show the picked
  task's name. `Request from` (the assignee field) stays a native
  `<select>` — the household is capped at a handful of users (see
  PROJECT_SPEC.md), so a short fixed list isn't the problem this
  solves. Verified with a mocked jsdom pass: opening the picker stacks a
  second `.modal-overlay`, category-chip and search filtering narrow the
  list (independently and together), picking a task prefills the parent
  modal and closes the picker, and picking "Custom (one-off)" resets the
  fields back to their defaults.
- 🐛 Fixed the floating bulk bar covering the task it's about to act on:
  entering bulk-select mode on Home now measures the actual rendered
  `.bulk-bar` height (`getBoundingClientRect`, since it varies with font
  size/viewport — a guessed constant would drift) and adds that much
  bottom padding to `.page`, so the last row (and the pagination controls
  below it) stay fully visible above the bar instead of partly hidden
  behind it; the padding clears again on exiting selection mode. Visual/
  pixel verification needs a real browser (jsdom has no layout engine —
  `getBoundingClientRect()` always reports 0 there); confirmed instead
  that the mechanism fires — the padding appears the moment the bar
  shows and clears the moment it's dismissed — and relied on a sensible
  floor (64px) under the measured height for that reason too.
- ✅ Added **pagination to Home's "All tasks" list** — it was fetching
  and rendering every active task unconditionally regardless of
  search/category filters. Pagination is purely client-side (slices the
  already-fetched, already-filtered array; no new network call per
  page) since a household's task list, unlike storage's inventory, isn't
  at a scale a server round-trip per page would pay for — reconsider
  this if that stops being true. Same `PAGE_SIZE=20` convention and
  `.pagination`/`.page-label` CSS already used by storage's item grid
  (the classes existed in `components.css` unused until now). Controls
  only render once the filtered count exceeds `PAGE_SIZE`, per the
  request that a short list not show pagination it doesn't need;
  changing the search or category filter resets back to page 1.
  Verified with a mocked jsdom pass: no controls under the threshold,
  correct page contents/counts/button-disabled-state across a 3-page
  (45-task) list including the partial last page, and narrowing a
  search back under the threshold both collapses the controls and
  proves the offset reset (the matched rows still render instead of
  silently slicing into empty space at a stale page 2/3 offset).
- 🐛 Fixed break mode appearing to reset a user's own points to 0 on
  Home. It never actually did — `complete_task`/`complete_todo` don't
  check `on_break` at all, and `leaderboard_for_period` (what the weekly/
  monthly PDF reports use) never excluded break users either, so reports
  always correctly included whatever they'd earned. The *display* bug
  was narrower: Home's "Points this week" card and weekly-goal bar both
  sourced their number from `GET /points/leaderboard`, and `crud.
  leaderboard()` excludes on-break users ENTIRELY (by design — that's
  the actual "hide from the leaderboard" behavior, correct for the Stats
  page's comparison view) — so a break user's own row was simply absent
  from the list Home searched, and `mine ? mine.total_points : 0`
  silently fell back to 0. Fixed by giving `leaderboard()` an optional
  `include_user_id` that punches one specific user back into the
  results regardless of break status, and a new `include_me=true` query
  param on `GET /points/leaderboard` that resolves to the caller's own
  id server-side (never a client-supplied id, so it can only ever
  un-hide yourself, not spoof another break user back into view). Home
  now passes `include_me=true`; the Stats page's own call is untouched,
  so break users stay correctly hidden from everyone else's leaderboard/
  heatmap-household-view/balancer-eligibility exactly as before — only
  the viewer's own "how am I doing" number stops reading 0 for no
  reason. Verified live end-to-end: a test user earned 15 points, went
  on break, then correctly disappeared from the general `/points/
  leaderboard` while her own `include_me=true` call still showed the
  real 15 (confirmed a DIFFERENT user's `include_me=true` call does NOT
  leak her back in), and the weekly PDF report — downloaded and
  visually read — listed her with her full 15 points/€15.00 despite the
  break, confirming the "still receives earned points" report behavior
  was already correct rather than assuming it from a code read alone.
  Also confirmed with a mocked jsdom pass on Home itself (request
  carries `include_me=true`, stat card and goal bar both show the real
  total instead of 0 for an on-break user). All test fixtures (users,
  points entries, the generated test report and its PDF file — no
  `DELETE /reports/{id}` endpoint exists, so that one needed a direct
  SQL+volume cleanup) were removed afterward.
- ✅ **Configurable week start, auto-generated weekly reports, a "paid"
  toggle, and a "Last week" chip** (PROJECT_SPEC.md "Admin tools").
  - `HouseholdSettings.week_start_weekday` (0=Mon..6=Sun, admin-editable,
    default 0/Monday — the hardcoded behavior this app always had
    before). One new pure function, `crud.week_bounds(d, week_start)`,
    is now the SINGLE place every weekly computation in the service
    resolves a week's Monday-Sunday-shaped bounds from — points-this-
    week, the leaderboard's This/Last week filters, the balancer's
    weekly period, the nudge, and auto-generated reports all go through
    it, so they can't disagree with each other about where a week
    starts. 7 new unit tests (`tests/test_week_bounds.py`): every start
    weekday, the date landing exactly on a week's first/last day, a year
    rollover, and purity.
  - `GET /points/leaderboard` gained a `period` param
    (`this_week`/`last_week`/`this_month`/`all`), resolved server-side
    in UTC against the live setting (`crud.resolve_leaderboard_bounds`)
    — replaces client-side date math in Home/Stats that (a) had the same
    local-vs-UTC gap as the `dueBadge` bug fixed earlier this session and
    (b) couldn't have known the week-start setting without an extra
    round-trip anyway, since Home fetches `/settings` and the
    leaderboard in the same `Promise.all`. `since`/`until` still work
    directly if passed. `startOfWeekIso`/`startOfMonthIso`/
    `lastWeekRangeIso`/`todayWeekday` are gone from `util.js` — dead
    once Home and Stats stopped needing them (the last one had already
    lost its only caller when Home's "Today" section was removed).
  - **Blocking trap caught before it shipped**: the balancer matched
    existing `TaskAssignment`s by an exact `(task_id, period_start)` —
    changing `week_start_weekday` mid-period shifts what "this week's
    start date" resolves to, which would have silently double-assigned
    every weekly task on the next run. Switched to an overlap check
    (`period_start <= as_of <= period_end`) instead, which also
    simplified the "already has an assignment this period" lookup to a
    plain task-id set. Verified live: assigned a task under one
    week-start setting, changed the setting, re-ran the balancer — no
    duplicate assignment, confirmed via `GET /assignments` too.
  - **Another trap caught**: `PUT /settings` replaces the whole row, and
    `update_settings`/`admin.js`'s `patchSettings` both assign/merge an
    explicit field list — adding the two new settings fields to the
    schema without adding them to *both* of those would've meant saving
    the goal silently reset the week start back to Monday. Fixed in both
    places; verified live (and with a mocked jsdom pass) that saving one
    setting doesn't disturb the other.
  - `HouseholdUser.role` — a nullable, non-authoritative cache of the
    JWT's role claim, synced in `main._self` (called on nearly every
    route) whenever it differs. Never used for authorization — always
    the live token for that, same as everywhere else in this app — it
    exists purely so a background job can know who's an admin to
    push-notify without a live request to check against. Verified via
    `/me` calls from both an admin and a user token, confirmed against
    the DB.
  - `Report.generated_by_id` is now nullable (migration relaxes
    NOT NULL → nullable, always a safe change) for reports the scheduler
    generates with nobody behind it; `ReportOut.generated_by` is
    `None`/omitted and the PDF credits "Automatic" instead of a name.
    `Report.paid_at` (nullable timestamp; null = unpaid) tracks the new
    paid toggle — `PATCH /reports/{id}` with `{paid: bool}`, admin-only.
  - `crud.run_scheduled_auto_report_if_due` (new hourly scheduler tick,
    `HouseholdSettings.auto_report_enabled`, off by default) is a
    **catch-up check, not a weekday/hour match**: due whenever the week
    before the current one hasn't had its report generated yet, so it
    still fires correctly even if the server was down right when a week
    rolled over, instead of silently missing that week forever. Skips
    generating (but still stamps `last_auto_report_period`) if an admin
    already generated that exact period manually, so there's never a
    duplicate PDF for the same week. Verified live by invoking it
    directly inside the container (`docker compose exec household-
    backend uv run python -c ...`, since waiting for a real hourly tick
    isn't practical): first call generated the correct "last week"
    report with `generated_by_id: None`; a second call in the same
    window correctly no-opped.
  - `crud.notify_new_report` pushes "New report generated" to admins
    only (via the cached role hint above), skipping whoever just
    generated it manually themselves — one push for the event, not a
    flood. `ReportOut.is_last_week` is computed server-side per request
    (against the *current* week-start setting, never stored) and drives
    the Admin panel's "Last week" chip; verified it correctly flips once
    the real week moves on, via the same live auto-report run (the
    report for the week before "today" was correctly flagged
    `is_last_week: true`).
  - Same date-key idempotency-stamp fix applied to the pre-existing
    nudge schedule while in the area: `last_nudge_sent_week` used to
    store an ISO-calendar-week string ("2026-W41"), inherently
    Monday-anchored — left as-is, a configurable week start would have
    silently stopped agreeing with the nudge's own "once per week"
    dedupe. Now stores the resolved week's start date instead, same
    format `last_balance_run`/`last_auto_report_period` already use.
    One disclosed, one-time side effect: the stored "2026-W41"-style
    value won't match the new key format, so the nudge may send once
    more than strictly necessary the first time it fires after this
    deploys.
  - Verified live end-to-end beyond the traps above: changing the
    nudge's weekly dedupe to date-based correctly no longer collided
    with mismatched week-start settings. All test fixtures (settings
    changes, test users, a test task, generated test reports and their
    PDF files, and a real pre-existing unclaimed board todo the live
    balancer run incidentally swept up and had to be unassigned again)
    were restored to an exact pre-test snapshot afterward.
  - **Admin UI**: a new "Week start" settings-section (a day picker);
    an "Auto-generate a report for each week once it ends" checkbox in
    the Reports section with a "last auto-generated" readout; each
    report row gained a "Last week" chip (when it applies) and a
    "Paid"/"Unpaid" chip, plus a "· auto" label for one nobody
    generated by hand. **Trap caught before it shipped**: report rows
    were `<button>` elements (whole-row click = download) — a `<button>`
    can't contain another interactive element, and the paid toggle
    needed its own button inside the row. Restructured rows as `<div>`s
    with two separate, explicitly-wired buttons (download, toggle-paid)
    instead of one row-level click handler, which also avoids the
    click-bubbling bug a nested button would have caused (tapping
    "mark paid" would otherwise have also triggered a download, since
    clicks bubble up through all ancestors including a row-level
    listener). Verified with a mocked jsdom pass: chips render
    correctly per report, the row is confirmed to be a non-button
    element holding exactly two real buttons, and tapping the paid
    toggle sends exactly one correctly-shaped `PATCH`.
  - **Previously disclosed gap, now fixed**: the Stats heatmap's weekday
    columns/labels and `stats.js`'s `buildWeeks()` were hardcoded
    Monday-first, not following a changed week start. `buildWeeks(days,
    weekStart)` now rotates the leading-padding count by `weekStart`
    (`crud.week_bounds`'s own 0=Mon..6=Sun convention) instead of always
    assuming Monday=0, and a new `dayLabels(weekStart)` rotates the
    label row (derived from `util.js`'s `WEEKDAY_LABELS`, trimmed to 2
    letters, instead of a second hardcoded "Mo Tu We..." string) to
    match. `loadHeatmap()` fetches `week_start_weekday` from the
    already-cached `GET /settings` call and renders the label row from
    it before building the grid. Verified by hand-tracing the rotation
    math for a Thursday week start (weekStart=3): a Monday day correctly
    lands in grid slot 4, matching "Mo" at index 4 of the rotated label
    row; the weekStart=0 (Monday, the default) case reduces to exactly
    the old hardcoded behavior, so existing installs see no change.
    Rebuilt and confirmed the updated file serves without a syntax
    error; no real browser available to visually confirm the rotated
    grid, same disclosed limitation as the rest of this frontend.
- ✅ **Corrected stale doc, not a new feature**: this file previously
  listed profile-picture upload as not built. It already is — `POST`/
  `DELETE /me/photo` (self), `GET /users/{id}/photo` (auth-gated, same
  pattern as storage's item images), `AVATAR_DIR`/`MAX_IMAGE_BYTES` in
  `main.py`, the `household-avatars` volume, and a dedicated migration
  (`57fad95d109c`, "add profile photo to household users") are all
  already in place, with the frontend side (Settings page: upload,
  "Remove photo", avatar preview via the same `fetchImageUrl` blob-URL
  pattern storage uses) already wired up too — found while auditing this
  file for accuracy during a production-readiness pass, not something
  changed this session.
- 🐛 **Fixed: viewers permanently cluttered the points leaderboard.**
  `crud.leaderboard()` only ever excluded on-break users; role was never
  part of the filter. Since `complete_task`/`complete_todo` both require
  `can_write` (admin/user only — `main.py`), a viewer can never actually
  earn a point, so once auto-provisioned they'd sit at a permanent,
  meaningless 0 on every leaderboard view forever. Fixed by also
  excluding `HouseholdUser.role == "viewer"`, using the same cached
  `role` hint `_self()` already keeps in sync (see that function's own
  docstring) rather than a live token check. Treats an unsynced `NULL`
  role as "not known to be a viewer" (included, not excluded) —
  structurally this should never actually happen (a `household_users`
  row can't exist without `_self()` having already run once, which sets
  `role` in that same call), but costs nothing to guard against a future
  row created some other way accidentally hiding a real admin/user.
  `include_user_id` (the "show me my own total regardless" override,
  originally built for break-mode) now also bypasses the viewer
  exclusion — a viewer checking their own `include_me=true` standing
  sees their real (0) total; everyone else's view of the leaderboard
  still excludes them. Verified live: a test admin user appeared at 0
  points (existing documented behavior for any non-viewer with no
  completions yet); a test viewer user was absent from the general
  leaderboard but appeared correctly in their own `include_me=true`
  view; a real pre-existing admin user's real 352-point total was
  unaffected. Test fixtures cleaned up afterward.
- ✅ **1.1.0: Chained tasks.** A new `TaskChainLink` table
  (`parent_task_id`, `child_task_id`, `same_user`, `position`, unique on
  the parent/child pair) lets a task define "when I'm completed, also
  spawn these" — e.g. "Set the table" → "Clear the table". Routes:
  `GET`/`POST /tasks/{id}/chain-links`, `DELETE
  /tasks/{id}/chain-links/{link_id}` (`create_chain_link` rejects a
  self-link, a duplicate, and — via a DFS over the existing link graph,
  `crud._reachable_task_ids` — anything that would close a cycle).
  - **Trigger is completion, not scheduling** — deliberately, to solve
    the "overscheduling" problem named in the request: a child only ever
    gets an instance when its parent actually happened, not on its own
    independent recurring schedule. Wired into both `crud.complete_task`
    (recurring Task) and `crud.complete_todo` (a todo, including one
    that was itself chain-spawned — so a chain can run multiple levels
    deep, A→B→C, each completion re-checking for its own further links).
    Each spawned child is a `TodoItem`, not a `TaskAssignment` — a chain
    child can legitimately happen more than once a day (every time its
    parent does), which `TaskAssignment`'s one-per-task-per-period
    uniqueness can't represent.
  - **`same_user=True`** assigns the spawned todo directly to whoever
    completed the parent, bypassing the balancer entirely.
    **`same_user=False`** assigns it immediately (not left for the next
    scheduled sweep) via the pure `balancing.balance()` function — the
    same fairness picture `run_balancing`'s own sweep uses
    (`crud._gather_balancer_load`, extracted out of `run_balancing` so
    both share one implementation) — always excluding whoever completed
    the parent. Left open/unassigned on the board if nobody else is
    eligible (everyone else on break), exactly like an ordinary sweep
    leftover; `TodoItem.exclude_user_id` persists that exclusion so (a)
    the daily sweep, if it later picks up the same still-unassigned
    todo, still won't hand it to the excluded person, and (b) that
    person can't just tap "claim" on the open board item to route around
    it (`crud.claim_todo`'s conditional UPDATE now also checks
    `exclude_user_id`).
  - **One source of instances.** A task reachable only as someone's
    chain child (`crud.is_chain_child`/`chain_child_task_ids`, derived
    live from the link table on every call, never a stored flag that
    could drift) is excluded from `run_balancing`'s own sweep candidates
    (it has no independent schedule to be swept for), from the Tasks
    page's implied "pick a child task" cycle-avoidance (chain children
    are filtered out of that selector), and `crud.complete_task` rejects
    completing it directly with a 409 — its points only ever come from
    completing the spawned todo. Creating a link also deletes the
    child's own open `TaskAssignment` for the current period, if it had
    one from before becoming a chain child.
  - Push notification (`notify_todo_assigned`) fires for a
    different-person spawn, not a same-person one (nothing to notify
    someone about assigning to themselves).
  - **Found and fixed one real bug via live testing** (not caught by the
    balancing unit tests, since it only manifests with existing load):
    `crud._assign_chain_todo_now` originally hardcoded
    `max_new_items_per_user=1` for its single-item `balance()` call —
    since `balance()`'s cap filter is `count[uid] < max_new_items_per_
    user`, anyone who already held even one existing item (count ≥ 1)
    was wrongly skipped as "over the cap," even when they were the only
    eligible candidate — the todo fell through to unassigned instead of
    being handed to them. Fixed by computing the cap as `max(load_count
    .values(), default=0) + 1`, which always exceeds everyone's current
    count for this one-item call. Reproduced and confirmed fixed against
    the live dev stack (self-minted local-admin JWTs, matching this
    project's established fake-IdP/self-signed-token live-testing
    pattern): same-person spawn, different-person spawn excluding the
    completer, a 2-level chain (A→B→C) via completing the spawned todo,
    cycle rejection, self-link rejection, duplicate-link rejection,
    direct-completion-of-a-chain-child 409, and the exclude_user_id
    self-claim block. Test fixtures (tasks, todos, a temporary local
    user) cleaned up afterward.
- ✅ **1.1.0: On-break exclusion from assignment, admin reassign, and
  takeover requests.** Three related small features, built together.
  - **On-break exclusion**: `crud._check_assignable` is now the one
    place that validates "can this person be handed this" — unknown
    user id, or `on_break=True` (→ 400 "{name} is on break"). Used by
    `create_todo`/`update_todo` (closing a pre-existing gap — assigning
    a todo to an on-break user was only ever stopped by the balancer
    skipping them, never by the direct-assignment path), the new
    `reassign_todo`, and takeover-request creation.
  - **Admin reassign** (`POST /todos/{id}/reassign`, `can_admin`,
    body `{assigned_to_id}`): a direct, no-consent handoff —
    `crud.reassign_todo`. Open todos only (including a currently
    unassigned one — this doubles as an admin "just assign it"
    control). Still respects a chain todo's `exclude_user_id` (the
    "not the parent's completer" fairness rule — an admin override
    shouldn't quietly undo that), and cancels any pending takeover
    request on the item (its "requester currently holds this"
    assumption just became stale). Deliberately scoped to board
    todos only, not recurring `TaskAssignment`s — "the board" in the
    request is the Board page, which only ever showed todos; reassigning
    a recurring assignment has no existing UI to anchor it to and would
    be a bigger feature (a new "who has what" admin view) than this
    batch's "small features and improvements" framing.
  - **Takeover requests** — a new `TakeoverRequest` table/migration
    (`takeover_status` enum; `CheckConstraint` ensuring exactly one of
    `todo_item_id`/`task_assignment_id` is set; two partial unique
    indexes, one per item-kind column, each `WHERE status = 'pending'`,
    so only one pending request can exist per item — a plain composite
    unique index wouldn't have worked here, since NULL-vs-NULL never
    counts as a duplicate in SQL, so two separate single-column partial
    indexes were needed instead of one). Routes: `POST /todos/{id}
    /takeover-requests`, `POST /assignments/{id}/takeover-requests`,
    `GET /takeover-requests?direction=incoming|outgoing`, `POST
    /takeover-requests/{id}/{accept,decline,cancel}` — all `can_write`
    (any writable user, admin or not — "Non-admins can use this too"
    was explicit in the request), ownership checked in the route
    (target-only for accept/decline, requester-only for cancel).
    - **create**: requester must currently hold the item; target can't
      be self, on break, a viewer (role is only a cached hint — see
      `HouseholdUser.role`'s own docstring — but good enough to fail
      clearly at creation instead of leaving a request that can never
      be accepted, since accept is `can_write`-gated), or a chain
      todo's `exclude_user_id`; only one pending request per item.
    - **accept** re-validates the requester still holds the item with
      a conditional `UPDATE ... WHERE <holder column> = requester`
      (same pattern as `claim_todo`) rather than a read-then-write —
      the holder can change out from under a pending request (admin
      reassign, the balancer's rebalance pass, the requester going on
      break). A lost race marks the request `cancelled` and returns
      409 rather than leaving it dangling in `pending`. For an
      assignment, accepting also stamps `reassigned_at` so the
      balancer's `rebalance()` pass won't immediately pull it back —
      verified live: ran `/balancing/run` again right after an
      accepted assignment takeover and confirmed the holder stuck.
    - **Stale-request cleanup**, so a pending request never outlives
      the situation it was about: `_release_user_assignments` (break
      mode) now also cancels any pending request where this user is
      the target (can't accept while on break), and any on a todo this
      user just lost (now unassigned) — a `TaskAssignment`-based
      request cancels itself automatically via `ON DELETE CASCADE`
      when break mode deletes the assignment outright.
      `run_balancing`'s rebalance pass cancels pending requests on
      whatever it just pulled away from its holder.
      `complete_todo`/`cancel_todo`/`reassign_todo` all cancel any
      pending request on that todo (can't take over something that's
      done, cancelled, or just changed hands).
    - Push notifications: target gets one when asked
      (`notify_takeover_requested`), requester gets one when the
      target answers (`notify_takeover_responded`) — both called from
      the route AFTER the crud function's own commit, same ordering
      fix applied to `_spawn_chain_children`'s notification below.
  - **Found and fixed one real bug while wiring this up (not new code,
    pre-existing since 1.1.0's chain-tasks work)**:
    `_spawn_chain_children` was calling `notify_todo_assigned` — which
    calls `push.send_to_subscriptions`, which commits internally to
    prune dead subscriptions — *inside* the loop that spawns chain
    children, before `complete_task`/`complete_todo`'s own final
    commit. With more than one chain link, this silently split one
    logical transaction (the points entry plus every spawned child)
    into several separate commits, undermining the atomicity the
    surrounding code's own comments promised. Fixed by having
    `_spawn_chain_children` return the children that need notifying
    instead of notifying them itself, so both callers now notify AFTER
    their own single final commit.
  - Verified live against the dev stack (self-minted local-admin/user
    JWTs, same methodology as the rest of this session): on-break
    users correctly rejected (400) by todo creation, reassign, and
    takeover-create; non-admin reassign correctly 403s, admin reassign
    works and still blocks an on-break or excluded target; the full
    takeover lifecycle (create → duplicate-pending rejection → wrong-
    user accept/cancel rejected with 403 → accept → verified the item's
    new holder) for both a todo and a recurring assignment; the
    accept-time race (simulated by changing the holder out from under
    a pending request directly in the database) correctly 409s and
    auto-cancels the request; both on-break cleanup paths (target going
    on break cancels an incoming request; requester going on break
    cancels an outgoing one on their now-unassigned todo); a completed
    multi-step UI flow in a real headless Chromium session (ask →
    accept on Home, admin reassign on Board) with zero console errors.
    Test fixtures cleaned up afterward.
  - **Follow-up fix, same 1.1.0**: while testing the takeover-request
    viewer exclusion, noticed `run_balancing`'s and
    `_assign_chain_todo_now`'s own `eligible` lists only filtered on
    `on_break`, never role — meaning a viewer could still end up
    holding a balancer-swept task or a chain-spawned todo (they just
    couldn't complete it themselves, same structural gap the 1.0.2
    leaderboard fix patched a *symptom* of). Flagged rather than fixed
    unilaterally at the time; the user confirmed it should be fixed.
    Both call sites now build `eligible` via a new shared
    `crud._is_eligible_for_tasks(user)` (not on break, not a viewer).
    Verified live: with every non-viewer user on break, a weekly task
    is correctly left unassigned (`unassigned_task_count: 1`) rather
    than handed to the one remaining viewer — before the fix this would
    have gone to them, since they'd read as the only/least-loaded
    "eligible" candidate. Test fixtures cleaned up afterward.

## Household service — frontend

- ✅ Built on the same vanilla HTML/CSS/JS conventions as
  `storage/frontend` — `css/tokens.css` is kept in lockstep (same
  black-and-white palette, dark theme, spacing/radius/shadow tokens),
  plus a new monochrome `--heat-0..4` scale for the activity heatmap so
  it stays within the b&w design rather than introducing a new hue.
  `js/auth.js`, `theme.js`, `toast.js`, `confirmDialog.js`, `main.js`
  are carried over unchanged; `api.js` is the same pattern minus the
  image-blob helpers (no photos in this domain).
- ✅ Six path-routed pages (`#/...` switched to clean `/...` URLs — see
  the storage-frontend entry above): **Home** (your points this week + weekly
  goal progress, an "Assigned to you" section covering both recurring
  Task assignments and assigned Board todos, full task list with
  one-tap complete/search/select-to-bulk-complete, category filters —
  there is deliberately no separate "Today" list: it only ever
  duplicated entries from the full task list one scroll up, with no
  behavior of its own, so it was removed rather than kept as
  a redundant filtered view), **Board** (the todo board —
  post/complete/cancel one-off requests, optionally directed at someone;
  the "New todo" modal's "From task" field is a popup picker, not a
  native `<select>` — see "Mobile-friendly picker dialogs" below — so
  posting an existing recurring task as a one-off board request doesn't
  mean retyping its title/description/points by hand; picking one
  prefills those three fields, still editable, and still creates a
  plain `TodoItem` with no link back to the `Task` row, matching the
  board's "one-off, decoupled from the recurring schedule" design),
  **Stats** (leaderboard by
  all-time/this-week/**last week** (a closed, final range)/month, with
  the EUR-equivalent shown next to each total when an admin has set a
  rate; a GitHub-style activity heatmap — weekday labels fixed outside
  the horizontally-scrolling grid and all 7 shown, not GitHub's
  Mon/Wed/Fri — household-wide/just-me toggle, recent-activity feed),
  **Tasks** (category + task management: points, a Daily/Weekly/Monthly
  "Repeats" picker — replaces the old "only on specific weekdays"
  checkbox, with the weekday grid now only shown for Weekly — and
  ramp-up bonus config), **Settings** (break-mode toggle, a
  push-notification toggle, read-only weekly goal, theme, account,
  logout — reached via a topbar icon now, not the bottom nav),
  **Admin** (`/admin`, admin-only: editable weekly points goal, a
  currency picker (EUR/USD/GBP/CHF/SEK/NOK/DKK/PLN/CZK/JPY/CAD/AUD) +
  conversion rate, a "send weekly reminder now" button plus an optional
  automatic weekly-reminder schedule (weekday + UTC hour, off by
  default) with a "last sent" readout, a "Run balancer now" button with
  a per-user result summary (new task/todo counts, expected points,
  leftover-unassigned counts), and generate/list/download PDF reports).
- ✅ Balancing tool, frontend side: Home gained an "Assigned to you"
  section (above Today) listing your current weekly/monthly task
  assignments with their period range, and every task row in Today/All
  tasks shows an "Assigned to you"/"Assigned to {name}" badge when one
  exists — both read `GET /assignments`. Home's Today filter now also
  correctly excludes `monthly` tasks (previously `!t.weekdays` would
  have shown them every day, same bug a daily task's missing `weekdays`
  would trigger). Board gained a Claim button (raised-hand icon) on any
  open, unassigned todo — `POST /todos/{id}/claim` — right next to
  complete/cancel; already-assigned/requested todos don't show it.
- ✅ Role gating mirrors storage's UX-only client-side pattern: viewers
  get every page read-only (no FABs, no select/complete/edit controls);
  the backend independently enforces the same rule. The weekly points
  goal goes one step further and is the one place this app actually
  distinguishes `admin` from `user` (both client-side — the Settings
  page only shows the Admin panel link to admins, and the router
  redirects a non-admin away from `/admin` — **and** server-side —
  `PUT /settings` now requires the `admin` role, not just `can_write`).
- ✅ Bottom nav is 4 tabs (Home/Board/Stats/Tasks); Settings moved to a
  gear icon in the topbar so the bar doesn't get cramped on narrow
  screens. Admin has no nav entry of its own — reached only via the
  link on Settings (admins) or `/admin` directly.
- ✅ Activity heatmap: weekday labels are a fixed column outside the
  horizontally-scrolling grid (previously they scrolled away with it —
  now they don't), and the grid opens pre-scrolled to the current day
  instead of the oldest one.
- ✅ Checked, not a bug: Stats' "Recent activity" was already properly
  limited, both ends — `stats.js` requests `GET /points/recent?limit=20`
  and the route caps `limit` itself (`ge=1, le=100`, default 20), so it
  was never loading every `PointsEntry` regardless of what the frontend
  asked for. Verified against the live backend's real data (55 rows at
  the time): no `limit` param and `limit=20` both correctly return 20;
  `limit=100` (the max) returns all 55, proving the cap tracks the
  requested count rather than coincidentally equaling it; `limit=500`
  (over the server's own bound) 422s instead of silently clamping — the
  backend enforces its own cap independent of whatever the frontend
  happens to send.
- 🐛 Fixed the leaderboard's period toggle (`#period-segmented`: All
  time/This week/Last week/Month) visibly colliding with the
  "Leaderboard" title on a narrow phone — 4 buttons with longer labels
  than any other segmented control in the app (vs. Activity's 2-button
  Household/Just me, which already fit) don't fit beside the title on
  one line. `.section-heading` gained `flex-wrap: wrap` generally
  (harmless for anything that already fits — it only kicks in when
  content doesn't), and `#period-segmented` specifically goes full-width
  with evenly-stretched buttons below the title on mobile, reverting to
  the normal compact inline-pill look everything else uses once there's
  room (`min-width: 560px`, the same breakpoint value already used
  elsewhere in this file). This is a pure CSS/layout change with no
  real browser available in this environment to confirm the pixel
  result — reasoned through standard, well-defined flexbox behavior
  (an explicit `width: 100%` on a flex item forces it onto its own line
  in a wrapping row container) rather than visually verified; worth a
  quick look on an actual phone.
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
  by role), the `/admin` router redirect, and viewer-role control
  hiding on every page. No real browser was available in this
  environment to eyeball it visually — functionally verified, not
  visually (heatmap auto-scroll-to-today in particular: the code path
  is exercised, but jsdom has no real layout engine, so the actual
  visual scroll position is unverified).
- 🐛 Fixed loading skeletons flashing on fast (typical, local-network)
  responses across every page in this frontend — same fix/rationale as
  storage's own entry above, `showSkeletonAfterDelay(root, html,
  delayMs = 200)`, here added once to the shared `util.js` (not
  duplicated per file, this frontend's existing convention for anything
  more than a one-line helper) and imported wherever a loader shows a
  skeleton: Home (stat cards — now built empty in the initial template
  and filled in by `loadStats` itself rather than inline HTML, same
  reasoning as the fix below applies to a first-paint skeleton as much
  as a reload one — "Assigned to you", the task list), Board (the todo
  list), Admin (all four settings sections), Settings (break mode, push
  notifications, the read-only household-settings row), Tasks (the task
  list), and Stats (the leaderboard, recent activity). A response faster
  than the delay cancels the pending timer before it ever fires, so
  nothing renders at all; a genuinely slow one still shows the skeleton,
  just not from the first instant. Verified with a mocked jsdom pass
  (the helper in isolation, plus Home's stat cards end-to-end for both a
  fast response that never shows a skeleton and a deliberately slow one
  that does, then clears correctly once real content arrives).
- ✅ **Installable to homescreen** (PROJECT_SPEC.md — the one spec item
  that had never been built). New `manifest.json` (`name`/`short_name`,
  `start_url: "/home"`, `display: "standalone"`, `background_color`/
  `theme_color` matching the app's white default theme) plus a new
  `icons/` directory: 192×192 and 512×512 PNGs (`purpose: "any"`), a
  separate 512×512 `purpose: "maskable"` variant with extra padding so
  the glyph stays inside the safe zone when an OS crops it to a circle
  or squircle, and a 180×180 `apple-touch-icon.png` (iOS ignores the
  Web App Manifest's own icons entirely and needs its own `<link
  rel="apple-touch-icon">` plus `apple-mobile-web-app-*` meta tags to
  behave like an installed app rather than a bookmarked Safari tab —
  all added to `index.html`). Icon art: a bold white checkmark on the
  app's `--color-text` near-black, generated from a small master SVG
  (shipped alongside the PNGs in `icons/` for future edits) via
  `rsvg-convert` — deliberately a single bold glyph rather than a
  literal copy of the thin-stroke `checklist` UI icon, since a 2px
  stroke turns to mush at a 48px home-screen size. No offline
  caching/fetch handler added to `sw.js` — PROJECT_SPEC.md scopes this
  feature to installability only ("not necessarily full offline
  support"), and the existing push-only service worker already
  satisfies Chrome's installability requirement of having one
  registered at all.
  `Dockerfile` copies `manifest.json` and `icons/` into the image;
  no `nginx.conf` change needed — `.json` is already in nginx's
  default `mime.types` (serves as `application/json` out of the box)
  and `.png` already matches the existing image-caching regex
  location. Verified live: rebuilt the container, curled
  `manifest.json` and all four icon files (200, correct content-types,
  correct pixel dimensions), and — able to go further than every
  earlier "no real browser available" disclosure in this file, since a
  headless Chromium turned out to be available in this environment —
  loaded the real page in headless Chromium at a 390px phone width and
  took an actual screenshot, confirming the login page renders
  correctly rather than just passing a jsdom-mocked assertion.
- 🐛 **Fixed (1.0.3): a renamed Authentik group left the renamed-to admin
  stuck on `viewer` client-side**, even though the backend was already
  authorizing them correctly. Root cause: `js/auth.js`'s
  `ROLE_FROM_GROUPS` was a hardcoded mirror of the generic default
  group names, shipped alongside 1.0.1's admin-editable backend mapping
  but never made to read it — so saving a custom `admin_group` through
  the panel updated the backend (verified correct: an admin-only route
  called directly with the same bearer token returned 200) but left
  this frontend constant untouched, silently falling through to
  `"viewer"` for any group name it didn't recognize. Worse than a
  cosmetic mislabel: the router's `/admin` guard reads
  `getCurrentUserInfo()` too, so this actively blocked the real admin
  from ever reaching the Admin panel through the UI, not just showing
  them a wrong badge.
  - **Diagnosed on a real production deployment**, not reproduced
    locally first: confirmed the configured `admin_group` and the
    actual Authentik group name matched exactly (`GET
    /authentik-config` vs. Authentik's own Groups page), confirmed
    group *membership* was correct too, then had the user decode their
    own live token in the browser console
    (`JSON.parse(atob(localStorage.getItem("hs_token").split(".")[1]...))`)
    — `svc-household-system-admins` was sitting right there in
    `groups`, ruling out every config-side explanation. The decisive
    check: calling an admin-only route directly from the browser
    console with that same stored token (`fetch("/api/household/reports",
    {headers: {Authorization: "Bearer " + localStorage.getItem("hs_token")}})`)
    returned 200 — proving the backend was correct and isolating the
    bug to the frontend's own role display/routing.
  - **Fix**: `getCurrentUserInfo()` now reads a module-level
    `groupRoleConfig` (same `admin_group`/`user_group`/`viewer_group`
    shape, and the same fixed admin > user > viewer precedence, as
    `shared.auth._role_from_groups` — previously this frontend copy
    used "whichever recognized group the token lists first," an
    accident of the old hardcoded dict's lookup order, not a real
    design). A new `warmGroupRoleMap()` fetches the real values from
    the same `/authentik-config` this file's `getAuthentikConfig()`
    already calls for the OIDC flow, and updates that module-level
    config on success. Deliberately starts at the old generic defaults
    (safe fallback before the first fetch resolves or if it fails) and
    is called from `main.js`'s `boot()` **without `await`** — an
    unreachable auth service must not delay the very first render, the
    same principle behind every other network call in `auth.js` (see
    `fetchWithTimeout`'s own comment) — so it self-corrects within the
    same page load once the fetch resolves rather than blocking
    startup. The brief window before it resolves only matters for
    role-gated UI a user couldn't reach that fast anyway (reaching
    `/admin` needs at least one more navigation/render cycle).
  - **Verified with a real reproduction of the exact bug**, not just
    code review: a jsdom test imported the actual, unmodified
    `auth.js` from both frontends, stored a fake-but-decodable token
    carrying `groups: ["svc-household-system-admins"]` (mirroring the
    real token's custom, non-default group name), and asserted
    `getCurrentUserInfo().role` was `"viewer"` *before*
    `warmGroupRoleMap()` resolved — reproducing the live bug exactly —
    then `"admin"` immediately after, on the same token, with no other
    change. Ran against both frontends' copies (kept byte-identical,
    the established convention). Hit an unrelated jsdom/Node version
    incompatibility in this environment (`atob`/`btoa` throwing on
    valid input) while building the test harness — worked around with
    a `Buffer`-based polyfill in the test only; not a real app bug,
    the actual app runs these in a real browser, already verified
    separately via headless-Chromium screenshots earlier this session.
- ✅ **1.1.0: Chained-tasks UI.** The Tasks page's edit-task modal grew a
  "Chain tasks" section (existing-task edit only — a link needs a real
  parent id) listing that task's chain links with a remove button, plus
  an add control (a select of eligible child tasks — excludes itself,
  anything already linked to it, and any task that's already someone
  else's chain child, to keep the obvious cycle case out of the picker
  entirely rather than relying on the backend's 400) and a same/
  different-person select. A task that's someone else's chain child
  shows a "Chained" badge in the Tasks list. Home's "Assigned to you"
  and the Board both label a chain-spawned todo "After: {parent task
  name}" instead of the generic "From the board" (`TodoOut
  .chain_parent_task_name`). Completing a task now also refreshes
  "Assigned to you" on Home (`afterTaskCompletion` now calls
  `refreshMyTodos`/`renderAssignedToYou`, not just the stats/task-list
  refresh it already did) — without this, a same-person chain spawn
  wouldn't show up there until an unrelated reload. Verified against
  the live dev stack with Playwright + the system's actual Chromium
  binary (not a mocked DOM): created a parent/child task pair, added a
  chain link through the real modal, confirmed the child picked up the
  "Chained" badge after a reload, completed the parent, and confirmed
  the spawned todo appeared on the Board with the correct "After: …"
  label and assignee, with zero console/page errors throughout. Test
  tasks/todos cleaned up afterward.
- ✅ **1.1.0: On-break hiding, admin reassign, takeover requests UI.**
  - Every "assign this to someone" picker (Board's "Request from" on a
    new todo, the new admin reassign modal, the new "ask someone to
    take over" modal) filters out on-break users client-side
    (`assignableUsers()` in board.js, inlined in home.js) — the
    backend's `_check_assignable` is still the real enforcement, this
    is just so the option isn't offered in the first place. The user
    list backing these pickers is now force-refetched each time one of
    these opens (`loadUsers(true)`) rather than the page-load-cached
    list the Board already had — break status changes often enough
    that a stale cache would show someone who's since gone on break.
  - Board rows gained an admin-only reassign button (the new `swap`
    icon) next to claim/cancel/complete, gated on
    `getCurrentUserInfo().role === "admin"` the same way Tasks/Admin
    already gate admin-only controls — opens a small picker, posts to
    `POST /todos/{id}/reassign`.
  - Home gained a "Takeover requests" section above "Assigned to you"
    (hidden entirely when there are none pending) listing incoming
    requests with Accept/Decline. Every row in "Assigned to you" — both
    the recurring-assignment rows and the board-todo rows — now renders
    either an "ask someone to take over" button or, if one's already
    pending, an "Asked {target}" badge with a cancel control
    (`takeoverControls()`, shared by both row shapes since both post to
    their own `/todos/{id}/takeover-requests` or `/assignments/{id}
    /takeover-requests`). A completion/claim/accept doesn't leave stale
    pending-request state on screen — every action that changes this
    state refetches both the assignment/todo lists and the takeover
    lists together (`afterTakeoverAction`).
  - Verified in a real headless Chromium session end to end: admin asks
    uitest2 to take over a board todo → "Asked uitest2" badge appears
    on admin's own "Assigned to you" row → uitest2 sees it under
    "Takeover requests" on their own Home → accepts → item moves to
    their "Assigned to you" → admin reassigns it back via the Board's
    new button. Zero console/page errors throughout. Test fixtures
    cleaned up afterward.
  - **Follow-up, same 1.1.0 — user feedback: "can't really tell the
    difference" between reassign and a takeover request, and couldn't
    ask for one from the Board at all.** Three fixes:
    - The reassign icon (`icons.swap`) and the ask-to-take-over icon
      got visually separated — ask now uses a new `icons.send` (paper
      plane) instead of also being `swap` — plus explicit tooltips:
      reassign says "moves it instantly, no approval needed"; ask says
      "they'll need to accept before it moves."
    - The Board now offers "ask to take over" too, not just admin
      reassign — on any open row the viewer currently holds
      (`todo.assigned_to.id === me.id`), writable or admin alike. This
      needed the Board to start tracking who "me" is at all
      (`meCache`, fetched via `/me` alongside the todo list) and to
      fetch outgoing requests the same way Home does, so a pending ask
      shows the same "Asked {target} [cancel]" state there too.
    - Extracted the actual modal + pending/cancel row-builder (previously
      duplicated between home.js's `takeoverControls`/`openTakeoverModal`
      and the new Board code) into a shared `household/frontend/js
      /takeover.js` (`takeoverControl()`, `outgoingRequestFor()`) — both
      pages now import the same implementation instead of drifting.
    - Verified live (mobile viewport, Playwright): the Board row for an
      item admin holds shows both the send and swap icons with the
      expected tooltip text; asking from the Board opens the same modal
      Home uses. Zero console errors.
- ✅ **1.1.0 follow-up: mobile-friendly chain-task picker.** User
  feedback: the chain-link "pick a child task" native `<select>` would
  flood with every task in the household on a real-sized list. Fixed by
  reusing board.js's existing task-picker popup (search box + category
  chips + scrollable list) instead of a native dropdown — extracted it
  out of board.js into a shared `household/frontend/js/taskPicker.js`
  (`openTaskPickerModal()`, parameterized with an optional `customOption`
  row so board.js's "Custom (one-off)" escape hatch still works, and an
  optional `title`/`emptyMessage`), so it's no longer board.js-only.
  Tasks.js's chain-link section now opens this picker from a button
  instead of a `<select id="chain-child-select">`. Verified live at a
  390px mobile viewport with Playwright and 15+ candidate tasks: the
  picker opens, search narrows the list, category chips filter it,
  picking a task sets the add button's target and label, and adding
  the link works end to end — zero console errors. (While debugging an
  apparent search-filter miss during this verification, traced it to a
  stale test assumption, not a real bug — a task that an *earlier* test
  run in the same session had already linked as a chain child was
  correctly excluded from the picker's candidate list; re-tested
  against an unlinked task and confirmed search filtering narrows the
  list exactly as expected.) Test fixtures cleaned up afterward.
- 🐛 **Fixed: picking a chain task and pressing Save silently didn't
  chain it.** User report: "I select the task to be chained and press
  save → No result, task stays unchained." Root cause was a UX trap the
  mobile-picker refactor above introduced: picking a task in the popup
  only staged it (set a label, enabled a separate "Add chain task"
  button) — it didn't persist anything. A user who pressed the Edit
  Task modal's main **Save** button afterward, reasonably assuming the
  pick was already part of the form state being saved, got no chain
  link and no error, since Save only ever persisted the task's own
  fields. Fixed by collapsing pick-and-add into one action — picking a
  task in `taskPicker.js`'s popup now immediately posts the chain link
  and refreshes the list, with no separate confirm step to forget.
  Verified live: picked a task, pressed **only** the main Save button
  (not any chain-specific control, reproducing the reported flow
  exactly) — the link was already attached, and survived a full page
  reload. Test fixtures cleaned up afterward.
- ✅ **1.1.0 follow-up: notification inbox.** A bell icon next to
  Settings in the topbar (`household/frontend/index.html`, wired from
  `household/frontend/js/notifications.js`) — a persistent, checkable
  inbox on top of the one-shot Web Push notifications this app already
  sent. Currently surfaces incoming takeover requests (the only
  notification kind that exists so far), each **actionable right from
  the panel** — Accept/Decline without navigating to Home. A numeric
  badge (polled every 30s, plus refreshed immediately after any
  takeover action anywhere in the app) shows the pending count, capped
  at "9+". Hidden entirely for a viewer (and before login) — a viewer
  can never be a takeover request's target (`crud._validate_takeover_
  target`), so their inbox is structurally always empty.
  - `api.get()` gained an optional `options` passthrough (previously
    `post`/`put` had it, `get` didn't) so the 30s poll can pass
    `{silent: true}` and not toast a "network error" on every
    transient hiccup, the way an interactive action correctly does.
  - **Local login doesn't reload the page** (`navigate("/home")`, not a
    real browser navigation — unlike the Authentik redirect flow,
    which does), so the one-time `initNotificationInbox()` call from
    `main.js`'s `boot()` can't just check "is this a writable user" once
    at startup and be done — at boot time, before login, nobody's
    logged in yet. Fixed by having `refreshNotificationBadge()` (not
    just the one-time init) re-check role on every call, including
    every poll tick, so the bell self-corrects within 30s of a login
    either way; `login.js` also calls it directly right after a
    successful local login so it doesn't have to wait that long.
  - Verified live: badge shows the correct count for a real pending
    request, the panel lists it with the requester's name, Accept from
    the panel moves the item and clears both the panel and the badge,
    and the bell stays hidden for a viewer-role token. Zero console
    errors. Test fixtures cleaned up afterward.
- ✅ **1.1.0 follow-up: confirm-and-override completing a chain-child
  task directly.** User request, after clarifying between three
  readings of the ask (completing directly / editing its schedule /
  chaining it twice — the user picked the first): tapping Complete on a
  task that's someone's chain child used to be a flat, unexplained 409.
  Now Home shows a confirm dialog naming which task(s) chain it (new
  `GET /tasks/{id}/chain-parents`, the reverse of chain-links — backed
  by a new `crud.list_chain_parents`/`ChainParentOut`) and asks "Complete
  it directly anyway?"; confirming sends `TaskCompleteRequest.force:
  true`, which is the only thing `crud.complete_task`'s existing
  chain-child check now accepts as a bypass (`if is_chain_child and not
  force: raise ...`) — every other rule (the `times_per_day` cap,
  ramp-up bonus, chain-spawning the task's own children) still applies
  exactly as normal. Home's task rows also gained the same "Chained"
  badge the Tasks admin page already had, so this is visible before
  tapping Complete, not just after. Deliberately does **not** auto-
  cancel any already-spawned, still-open todo for the same chain link —
  with `times_per_day` > 1 or multiple same-day parent completions,
  more than one could legitimately still be outstanding, and guessing
  which one(s) to cancel risks losing a real occurrence; the person
  confirming the dialog is making the same kind of judgment call
  `times_per_day` already leaves to them. Verified live: the dialog
  shows the exact expected parent name; Cancel leaves the task
  untouched; confirming awards points and marks it "Done today"; the
  raw API confirms a force:false request still 409s and force:true
  succeeds. Test fixtures cleaned up afterward.
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
- ✅ Admin/user distinction is real but intentionally asymmetric across
  the two apps, confirmed via `grep -n 'Depends(can_admin)'`:
  **Storage** has none at all (admin = user everywhere) — by design,
  not a gap: the household is a trusted group and nothing in Storage's
  domain needs gatekeeping beyond logged-in-vs-viewer (see
  `PROJECT_SPEC.md`). **Household** gates 7 routes to admin-only
  (`can_admin = require_role("admin")` in `main.py`) — weekly
  goal/money-rate/reminder-schedule settings, running the balancer on
  demand, generating a report, marking one paid, and the Authentik
  connection panel — because those genuinely are settings one person
  should own, unlike anything in Storage. Local-account user management
  (`auth`'s `POST /users`, also admin-only) still has no UI in either
  frontend — API only.

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
- ✅ Local dev CORS/proxy routing: works when pointing `config.js`
  directly at exposed backend ports (the commented-out fallback lines
  in both `config.js`); production routing of `/api/*` is now handled
  by each frontend's own nginx (see the proxy entry below), so the
  external Caddy only needs one `reverse_proxy host:port` line per app
  — documented in both frontend READMEs, including the exact bind-IP
  caveat for a Caddy that runs outside Docker (confirmed true of this
  user's own setup: Caddy in a separate Proxmox LXC).
- ✅ **Both frontends' own nginx now proxy `/api/*` internally**, so the
  external Caddy reverse proxy no longer needs a per-backend `handle`
  block. `storage/frontend/nginx.conf` gained `location /api/auth/` →
  `auth:8000` and `location /api/storage/` → `storage-backend:8000`
  (plus a 10MB `client_max_body_size` on the storage one, for item
  photo uploads); `household/frontend/nginx.conf` gained the matching
  `/api/auth/` and `/api/household/` → `household-backend:8000` blocks,
  ahead of its existing `/sw.js` no-cache rule. Both use nginx's
  trailing-slash `proxy_pass` prefix-stripping (the same idiom Caddy's
  `uri strip_prefix` + `reverse_proxy` already did) and forward
  `Host`/`X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto`. This means
  Caddy's own config collapses to one `reverse_proxy storage-frontend:80`
  / `reverse_proxy household-frontend:80` rule per app — the old
  multi-`handle` version is still documented as an alternative in both
  READMEs, for anyone who'd rather have the external proxy do that
  routing instead. Rebuilt both containers and verified live: from
  inside each frontend container, `/api/auth/health`,
  `/api/storage/health`, and `/api/household/health` each return
  `{"status":"ok"}` through the new proxy; also confirmed externally
  via the host-published `storage-frontend` port (`8080`).
  `household-frontend` has no published host port by default, so that
  one was checked via `docker compose exec` only.
  - Both frontends' `js/config.js` now default to the `/api/auth`/
    `/api/storage`/`/api/household` relative paths (the old direct-port
    `http://127.0.0.1:PORT` lines are kept, commented out, for anyone
    running the backends standalone without any proxy in front and
    willing to eat the CORS hit that implies).
  - **🐛 Real bug caught and fixed by this testing, not hypothetical**:
    a literal hostname in `proxy_pass` (no nginx variable) only
    resolves ONCE, at nginx's own startup — reproduced live by running
    `docker compose up -d --force-recreate storage-backend` (or
    `household-backend`) while the frontend container kept running:
    the backend came back up healthy and reachable by IP and by its
    host-published port, but the frontend's nginx kept 502ing every
    request by hostname, forever, since it never re-resolves on its
    own. Fixed in both `nginx.conf`s with `resolver 127.0.0.11 valid=10s;`
    (Docker's embedded DNS) plus a `set $xxx_upstream http://...;` +
    `proxy_pass $xxx_upstream;` per location, which forces a fresh
    resolve on every request instead of once at config load. Re-ran the
    same force-recreate test afterward: proxy survives it correctly.
    **Sub-trap caught in the same fix**: `set` must come *before*
    `rewrite ... break;` in the same location block — `break` halts
    every later rewrite-module directive, `set` included, so writing
    them the other way around left the variable permanently
    uninitialized and 500'd every request ("using uninitialized
    variable" in the nginx error log). Also fixed a second, independent
    bug the same investigation surfaced: `shared/entrypoint.sh` ran
    plain `uv run` for both the migration and uvicorn steps, which
    performs its own implicit sync-check on every container start even
    though the image's build stage already ran `uv sync --frozen` for
    that exact package — caught live when a force-recreated
    `household-backend` hung indefinitely mid-migration with 0% CPU;
    `/proc` on the stuck process showed it blocked on a `futex`, holding
    an open HTTPS connection out to a package-index CDN. Fixed by adding
    `--frozen --no-sync` to both `uv run` invocations, so container
    startup never has a network dependency it was never supposed to
    need — confirmed with a cold full-stack restart afterward: every
    backend reached "Uvicorn running" within a couple of seconds, no
    hung connections. **Bonus**: the `resolver`+variable fix also fully
    eliminated a separate cold-start race this same round of testing
    turned up — on `docker compose up -d` from a clean `down`, both
    frontend containers routinely start before their backend containers
    even exist yet, and the *old* literal-hostname config crashed nginx
    outright at boot with `host not found in upstream` (self-healing
    only because `restart: unless-stopped` retried it moments later,
    once the backend existed) — the new config never resolves eagerly
    at startup at all, so this no longer happens; verified with a full
    `down` + `up -d` cold start, checked both frontends' logs for the
    old crash message (none) and confirmed every service reached
    healthy within ~25s.

## Documentation

- ✅ `PROJECT_SPEC.md` — full design-decision summary (this session).
- ✅ `PROJECT_STATE.md` — this file.
- ✅ `MIGRATIONS.md` — Alembic workflow.
- ✅ `storage/frontend/README.md` — Authentik setup walkthrough + known
  gaps/notes.
- ✅ `.env.example` — reorganized (Auth / Authentik OIDC / Local
  fallback auth sections), `AUTH_MODE` removed as it no longer exists.

## Summary of what's next (not started, no action taken yet)

1. The scheduler (`household_service/scheduler.py`) now has two tenants
   (the weekly nudge, the balancing run). Still built generically — reach
   for it before hand-rolling another background loop.
2. Household frontend was built but only functionally tested (jsdom +
   real HTTP calls, no real browser available in that session) — worth
   an actual visual pass in a browser, especially the activity heatmap,
   Web Push permission prompt/toggle, and mobile layout at narrow
   widths.
3. Optional smaller gap: "remove photo" on Storage items (Household's
   equivalent control already exists, see its own entry above). (Clean
   URL routing and the PWA manifest both shipped this session — see
   their own entries above.)
4. User's own action items: complete the Authentik-side GUI setup
   (provider, groups scope mapping, application, groups), add the
   household frontend's origin as an extra Redirect URI on that same
   provider, and set a real `VAPID_SUBJECT`/regenerate VAPID keys for
   production rather than the dev ones currently in `.env`. Production
   Caddy routing for `/api/*` no longer needs per-path setup on Caddy's
   side at all now (see the reverse-proxy entry above) — just a single
   `reverse_proxy` rule per app, pointed at the Docker host's LAN IP
   and published port if Caddy runs outside Docker (confirmed to be
   the case here: Caddy runs in its own Proxmox LXC, not a container on
   this Compose project's network).
5. Auto generate fallback admin credentials on deployment to avoid
   unsafe passwords or forgetting to setup a fallback user.
