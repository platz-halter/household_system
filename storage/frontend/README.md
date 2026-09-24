# Storage frontend

Plain HTML/CSS/JS, no build step (ES modules loaded directly by the
browser) — matches the "not a webdev, keep it easy to maintain" goal.
Two pages: **Overview** (search/filter/sort/paginate items, view/edit,
bulk-add) and **Settings** (theme, account info, logout), plus a
**Login** page. Hash-based routing (`#/overview`, `#/settings`,
`#/login`) — no server-side rewrite rules needed, nginx just serves
static files.

## Wiring it to your Caddy reverse proxy

The frontend calls `/api/auth/...` and `/api/storage/...` on its **own
origin** (see `js/config.js`) — same-origin, no CORS to deal with. Point
Caddy at the three containers like this:

```caddyfile
storage.pressnet.duckdns.org {
    handle /api/auth/* {
        uri strip_prefix /api/auth
        reverse_proxy auth:8000
    }
    handle /api/storage/* {
        uri strip_prefix /api/storage
        reverse_proxy storage-backend:8000
    }
    handle {
        reverse_proxy storage-frontend:80
    }
}
```

Adjust the domain/VLAN specifics to match your existing setup (you're
already running Caddy for Authentik and Omada, so this slots into the
same pattern). Since it's a normal responsive page behind your existing
Caddy → Netbird → Authentik chain, it's reachable on the go the same way
your other services already are — nothing extra needed for that part.

If you'd rather test locally without touching Caddy yet, uncomment the
`ports:` line under `storage-frontend` in `docker-compose.yml` and the
`/api/*` paths in `js/config.js` won't resolve (no reverse proxy) — for
a quick local check, temporarily point `CONFIG.AUTH_BASE` /
`CONFIG.STORAGE_BASE` at `http://localhost:8001` / `http://localhost:8003`
instead (and uncomment those two services' `ports:` too). You'll hit
CORS doing it that way, so it's only useful for a quick sanity check.

## Adding a new theme

1. Copy the template block at the bottom of `css/tokens.css` into a new
   `[data-theme="your-id"] { ... }` block and fill in the variables.
2. Add `{ id: "your-id", label: "Your Theme" }` to the `THEMES` array in
   `js/theme.js`.

That's the whole process — the Settings page picks it up automatically.

## Notes / known gaps

- **Auth mode**: this login page only implements the local-account flow
  (`POST /token` on the auth service). Once Authentik is reachable,
  swapping to an OIDC redirect flow means replacing `js/login.js` — the
  rest of the app (role-gating, `/me`-equivalent via `decodeToken()`)
  doesn't change, since it already just reads `role` off the JWT
  regardless of who issued it.
- **Role source**: the frontend decodes the JWT client-side to decide
  what UI to show (hide the FAB / edit controls for viewers). This is
  UX only — the backend independently enforces the same rule, so a
  tampered token gets a 403 from the API either way.
- **Image editing**: uploading a new photo happens together with
  "Save changes" — there's no separate "remove photo" control yet.
- No offline / service-worker support yet (mentioned in the original
  design as "add to homescreen" — a `manifest.json` + icons would get
  you the install prompt; not done here since it wasn't asked for yet).
