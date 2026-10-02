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

## Authentik setup

The login page offers "Log in with Authentik" (primary) and a collapsible
local-account form (fallback) — both are always active on the backend
side (see `MIGRATIONS.md`'s sibling note in `shared/src/shared/auth.py`:
local and Authentik tokens are both verified on every request, chosen by
the token's own signing algorithm, not an env toggle).

In Authentik, create:

1. **An OAuth2/OpenID Provider**
   - Client type: **Public** (this is a browser SPA using PKCE — there's
     no client secret to protect)
   - Redirect URIs: the exact origin this frontend is served from, e.g.
     `https://storage.pressnet.duckdns.org/` (must match
     `AUTHENTIK_REDIRECT_URI` in `js/config.js` exactly, trailing slash
     included)
   - Signing key: set one (needed for the access token to be a real JWT
     the backend can verify via JWKS — without this Authentik may issue
     opaque tokens instead)
   - Scopes: the built-in `openid`, `profile`, `email`, **plus a custom
     one for groups** (next step)

2. **A custom Scope Mapping for group membership** — Authentik does not
   include group membership in the default scopes. Under
   *Customization → Property Mappings*, create a new **Scope Mapping**:
   - Scope name: `groups`
   - Expression: `return {"groups": [group.name for group in request.user.ak_groups.all()]}`

   Add this mapping to the provider's scopes, alongside the built-in
   ones.

3. **An Application** wrapping that provider, with slug
   `household-system` (matches the issuer path already used throughout
   this repo).

4. **The three groups** referenced in `shared/src/shared/auth.py`'s
   `GROUP_ROLE_MAP` (and mirrored in `js/auth.js`'s `ROLE_FROM_GROUPS` for
   display) — rename both copies together if you use different names:
   - `household-system-admins`
   - `household-system-users`
   - `household-system-viewers`

5. **Fill in the values** in `.env` (`AUTHENTIK_CLIENT_ID`,
   `AUTHENTIK_ISSUER`, `AUTHENTIK_JWKS_URL`) and `js/config.js`
   (`AUTHENTIK_CLIENT_ID` — same value as the backend's — plus the
   authorize/token/end-session URLs). If anything 404s, check
   `<issuer>/.well-known/openid-configuration` for the exact endpoint
   paths — they vary slightly by Authentik version.

Once working: Authentik-issued access tokens are typically short-lived
(often ~5 minutes); the frontend handles this with a silent
refresh-token exchange on a 401 (see `tryRefreshAuthentikToken` in
`js/auth.js`) — you shouldn't notice it happening. Local-account
sessions aren't refreshed this way (there's no refresh token for them);
a 401 there goes straight back to the login page.

## Other notes / known gaps

- **Role source for UI gating**: the frontend resolves the current
  user's role client-side (from the JWT's `role` claim for local
  accounts, or `groups` mapped through `ROLE_FROM_GROUPS` for Authentik)
  purely to decide what to show (hide the FAB / edit controls for
  viewers). This is UX only — the backend independently enforces the
  real rule from the same groups claim, so a tampered or stale-mapped
  token still gets a 403 from the API regardless of what the UI shows.
- **Image editing**: uploading a new photo happens together with
  "Save changes" — there's no separate "remove photo" control yet.
- No offline / service-worker support yet (mentioned in the original
  design as "add to homescreen" — a `manifest.json` + icons would get
  you the install prompt; not done here since it wasn't asked for yet).
