# Household frontend

Plain HTML/CSS/JS, no build step — same conventions as
`storage/frontend` (see that README for the full Authentik setup
walkthrough; it's one shared Authentik Application for the whole
system, so don't repeat that setup, just add this frontend's origin as
an extra Redirect URI on the same provider).

Five pages, all hash-routed (`#/home`, `#/board`, `#/stats`, `#/tasks`,
`#/settings`), plus `#/login`:

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
`/api/household/...` on its **own origin** (see `js/config.js`):

```caddyfile
household.pressnet.duckdns.org {
    handle /api/auth/* {
        uri strip_prefix /api/auth
        reverse_proxy auth:8000
    }
    handle /api/household/* {
        uri strip_prefix /api/household
        reverse_proxy household-backend:8000
    }
    handle {
        reverse_proxy household-frontend:80
    }
}
```

Since this is a **separate origin** from storage's frontend, add it as
an additional Redirect URI on the same Authentik provider (Authentik
providers accept more than one), and make sure `js/config.js`'s
`AUTHENTIK_REDIRECT_URI` resolves to it (it's computed from
`window.location.origin`, so this is automatic once Caddy routes the
right domain here).

For local testing without Caddy, uncomment the `ports:` line under
`household-frontend` in `docker-compose.yml` and point
`CONFIG.AUTH_BASE` / `CONFIG.HOUSEHOLD_BASE` in `js/config.js` at
`http://localhost:8001` / `http://localhost:8002` (you'll hit CORS
doing it that way — fine for a quick sanity check only).

## Notes / known gaps

- Role gating mirrors storage: the backend doesn't yet distinguish
  `admin` from `user`, so neither does this UI — viewers get a
  read-only version of every page, admin/user get full access
  everywhere, including category/task management and the weekly goal.
- No push notifications yet — the todo board's "request from a
  specific person" field is stored and shown, but nothing pings them.
- No PDF reports, no points→EUR conversion setting, no auto-balancing
  "assign tasks for me" tool — all still backend TODOs
  (`PROJECT_STATE.md`).
- No PWA manifest/installability yet, despite being in-scope per
  `PROJECT_SPEC.md`.
