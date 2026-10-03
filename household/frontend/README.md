# Household frontend

Plain HTML/CSS/JS, no build step — same conventions as
`storage/frontend` (see that README for the full Authentik setup
walkthrough; it's one shared Authentik Application for the whole
system, so don't repeat that setup, just add this frontend's origin as
an extra Redirect URI on the same provider).

Five pages, all clean path-routed (`/home`, `/board`, `/stats`,
`/tasks`, `/settings` — no `#/`), plus `/login` and an admin-only
`/admin`:

- **Home** — your points this week (+ progress toward the weekly goal,
  if one's set), today's scheduled chores with a one-tap "complete",
  and the full task list with search/category filters and a
  multi-select "complete selected" bulk action.
- **Board** — the one-off todo board: post a task requesting
  completion within N days (or today), optionally directed at a
  specific person; anyone can complete or cancel an open one.
- **Stats** — the points leaderboard (all-time/week/month), a
  GitHub-style activity heatmap (household-wide or just-you), and a
  recent-activity feed.
- **Tasks** — category and task management: points, weekday/frequency
  schedule, ramp-up bonus, which categories a task belongs to.
- **Settings** — break mode toggle, the household's weekly points
  goal, theme, account info, logout.

## Wiring it to your Caddy reverse proxy

Same pattern as storage — this frontend calls `/api/auth/...` and
`/api/household/...` on its **own origin** (see `js/config.js`). This
container's own nginx (`nginx.conf`) already proxies those two
prefixes to the `auth` and `household-backend` containers, so Caddy
itself needs only a single rule.

**If Caddy runs as its own container on the same Docker host**
(sharing this Compose project's network), point it at the container
name directly:

```caddyfile
household.pressnet.duckdns.org {
    reverse_proxy household-frontend:80
}
```

**If Caddy runs outside Docker** — its own VM/LXC, the actual setup
this repo was built against (Caddy in a Proxmox LXC) — it can't
resolve `household-frontend` as a hostname, since that only exists
inside this Compose project's own Docker network. Point it at the
Docker host's LAN IP and the published port (`8081` by default) instead:

```caddyfile
household.pressnet.duckdns.org {
    reverse_proxy 192.168.1.50:8081
}
```

(replace `192.168.1.50` with your actual Docker host's LAN IP — see
`storage/frontend/README.md` for the full explanation of why this
container's `ports:` binds to `0.0.0.0` rather than `127.0.0.1`: an LXC
has its own network namespace even on the same physical host/bridge,
so `127.0.0.1` there means the LXC's own loopback, not the Docker
host's.)

(See `storage/frontend/README.md` for the equivalent per-path `handle`
block version too, if you'd rather have Caddy do the `/api/*` routing
instead of this container's nginx — don't do both at once.)

Since this is a **separate origin** from storage's frontend, add it as
an additional Redirect URI on the same Authentik provider (Authentik
providers accept more than one), and make sure `js/config.js`'s
`AUTHENTIK_REDIRECT_URI` resolves to it (it's computed from
`window.location.origin`, so this is automatic once Caddy routes the
right domain here).

For local testing without Caddy at all, the `/api/*` paths already
work directly against the published port (`http://<docker-host>:8081/`,
or `http://localhost:8081/` on the Docker host itself) — no
`js/config.js` edit needed. Pointing `CONFIG.AUTH_BASE`/
`CONFIG.HOUSEHOLD_BASE` directly at `http://localhost:8001`/
`http://localhost:8002` instead (bypassing the proxy) still works too,
but you'll hit CORS doing it that way — fine for a quick sanity check
only.

## Notes / known gaps

- Role gating mostly mirrors storage: viewers get a read-only version
  of every page, admin/user get full access everywhere, **except** the
  weekly points goal — the one place this app actually distinguishes
  `admin` from `user` — which only admins can edit (enforced
  server-side too, not just hidden in the UI).
- Push notifications are built (Web Push via `sw.js` + VAPID): a todo's
  "request from a specific person" field pushes that person
  immediately, plus an optional automatic weekly reminder schedule, a
  balancer-run summary push, and a "new report generated" push to
  admins. Each device opts in separately via the toggle on Settings.
- PDF reports, points→money conversion (any ISO 4217 currency, not
  just EUR), and the auto-balancing "assign tasks for me" tool are all
  built — see the Admin panel and `PROJECT_STATE.md` for the details.
- Installable to the homescreen: `manifest.json` + `icons/` (192/512/
  maskable/apple-touch variants). "Add to Home Screen" in Chrome/Safari
  should offer a standalone app icon rather than just a bookmark.
- Functionally tested end-to-end (jsdom + real HTTP calls against the
  live backend). Confirmed the page itself renders correctly in a real
  (headless) browser at phone width, but nobody's eyeballed it
  interactively on an actual phone yet — worth doing, especially the
  heatmap and the newly-added install prompt.
