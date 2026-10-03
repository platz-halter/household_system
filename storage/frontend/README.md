# Storage frontend

Plain HTML/CSS/JS, no build step (ES modules loaded directly by the
browser) — matches the "not a webdev, keep it easy to maintain" goal.
Two pages: **Overview** (search/filter/sort/paginate items, view/edit,
bulk-add) and **Settings** (theme, account info, logout), plus a
**Login** page. Clean path-based routing (`/overview`, `/settings`,
`/login` — `history.pushState`/`popstate`, no `#/`); nginx's SPA
fallback (`try_files ... /index.html`, see `nginx.conf`) serves
`index.html` for any of these on a direct load or refresh, so no
dedicated rewrite rules were needed beyond what was already there.

## Wiring it to your Caddy reverse proxy

The frontend calls `/api/auth/...` and `/api/storage/...` on its **own
origin** (see `js/config.js`) — same-origin, no CORS to deal with. This
container's own nginx (`nginx.conf`) already proxies those two prefixes
to the `auth` and `storage-backend` containers, so Caddy itself needs
only a single rule per app.

**If Caddy runs as its own container on the same Docker host** (sharing
this Compose project's network, or attached to it), point it straight
at the container name/network and you don't need `storage-frontend`'s
published port at all:

```caddyfile
storage.pressnet.duckdns.org {
    reverse_proxy storage-frontend:80
}
```

**If Caddy runs outside Docker** — e.g. its own VM/LXC, which is the
actual setup this repo was built against (Caddy in a Proxmox LXC) —
it can't resolve `storage-frontend` as a hostname at all, since that
name only exists inside this Compose project's own Docker network.
Point it at the Docker host's LAN IP and the port this container
publishes (`8080` by default, see `docker-compose.yml`) instead:

```caddyfile
storage.pressnet.duckdns.org {
    reverse_proxy 192.168.1.50:8080
}
```

(replace `192.168.1.50` with your actual Docker host's LAN IP). This is
why `storage-frontend`'s `ports:` in `docker-compose.yml` binds to
`0.0.0.0` rather than `127.0.0.1` — an LXC has its own network
namespace even on the same physical host/bridge, so `127.0.0.1` there
means the LXC's own loopback, not the Docker host's.

Either way: adjust the domain/VLAN specifics to match your existing
setup (you're already running Caddy for Authentik and Omada, so this
slots into the same pattern). Since it's a normal responsive page
behind your existing Caddy → Netbird → Authentik chain, it's reachable
on the go the same way your other services already are — nothing extra
needed for that part.

If you'd rather have the *external* reverse proxy do the `/api/*`
routing instead of this container's own nginx — e.g. you want one less
layer to reason about — the old per-path `handle` blocks still work
too (same "container name" vs. "host IP" choice as above applies to
each `reverse_proxy` line):

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

— just don't do both at once, or you'll have two layers silently
agreeing with each other, which is harmless but pointless.

If you'd rather test locally without touching Caddy at all, the
`/api/*` paths work the same way directly against the published port
(`http://<docker-host>:8080/`, or `http://localhost:8080/` on the
Docker host itself) — no `js/config.js` edit needed, since it already
calls `/api/auth`/`/api/storage` as same-origin relative paths and this
container's own nginx handles the rest. You'll only hit CORS if you
instead point `CONFIG.AUTH_BASE`/`CONFIG.STORAGE_BASE` directly at
`http://localhost:8001`/`http://localhost:8003` (bypassing the proxy
entirely) — that still works, but you'll hit CORS doing it that way,
so it's only useful for a quick sanity check, not day-to-day dev.

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

5. **Fill in the values.** For a first deploy, set `AUTHENTIK_ISSUER`,
   `AUTHENTIK_JWKS_URL`, `AUTHENTIK_CLIENT_ID`, `AUTHENTIK_AUTHORIZE_URL`,
   `AUTHENTIK_TOKEN_URL`, `AUTHENTIK_END_SESSION_URL`, and
   `AUTHENTIK_SCOPE` in `.env` — that's now the ONLY place they need
   setting; neither frontend's `config.js` hardcodes any of these
   anymore (previously you had to edit both `.env` AND `config.js`
   with the same client ID, which is exactly the kind of drift that
   caused storage's frontend to have a blank `AUTHENTIK_CLIENT_ID` for
   a while without anyone noticing). After that first deploy, an admin
   can change any of these seven values from Household's `/admin` page
   (the "Authentik connection" section) instead of touching `.env`
   again — saving there requires a local admin's password as a second
   confirmation, and takes effect across every service within about a
   minute, no restart needed. If anything 404s, check
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
- Installable to the homescreen: `manifest.json` + `icons/` (192/512/
  maskable/apple-touch variants). No service worker — there's no Web
  Push feature here to justify one, and current browsers no longer
  require one for the install prompt itself, just the manifest.
