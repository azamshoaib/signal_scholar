# Deployment readiness

Per GitHub issue #29, the app is deployment-ready (every setting,
dependency, and start-command a real host would need is in place) even
though it isn't yet deployed to a live platform (blocked on the project
owner picking one and creating an account — see the follow-up issue
#47).

## Where the settings live

All of it is in `src/signal_scholar/settings.py`:

- `SECRET_KEY` reads `DJANGO_SECRET_KEY`, falling back to the existing
  `"django-insecure-dev-only-change-me"` dev-only value when unset.
- `DEBUG` reads `DJANGO_DEBUG` (a boolean env var, e.g. `"True"`/
  `"False"`), defaulting to `True` so local dev stays zero-config.
- `ALLOWED_HOSTS` reads a comma-separated `DJANGO_ALLOWED_HOSTS`,
  defaulting to `[]`.
- `STATIC_ROOT` and `STORAGES["staticfiles"]` (whitenoise's
  `CompressedManifestStaticFilesStorage`) plus `WhiteNoiseMiddleware` in
  `MIDDLEWARE` (directly after `SecurityMiddleware`) make static files
  production-ready.
- `src/signal_scholar/wsgi.py` is the standard Django WSGI entry point.
- The root `Procfile` runs `gunicorn signal_scholar.wsgi` for the `web`
  process — portable across common PaaS options, no platform pinned.

All three new env vars are documented in `.env.example` with their dev
default and what a real deployment must set instead.

## Verifying deployment readiness (no live host required)

Two commands stand in for a live deploy check until #47 provisions a real
platform:

```
DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=example.com \
  DJANGO_SECRET_KEY=<a long random value> \
  uv run python manage.py check --deploy
```

This should report no `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS` warnings
(`security.W009`, `W018`, `W020`) and no clickjacking warning
(`security.W002`). The remaining warnings (`security.W004`, `W008`,
`W012`, `W016`, `admin.W411`) depend on the eventual platform's TLS/domain
setup and are out of scope until #47.

```
DJANGO_DEBUG=False uv run pytest
```

This proves the app still works end-to-end (search, paper-detail, etc.)
without relying on Django's debug-mode conveniences.
`tests/conftest.py` runs `collectstatic` once per test session so pages
using `{% static %}` resolve correctly against whitenoise's manifest
storage — the same step a real deploy must run before starting the app.

## Deploying to Render + Supabase (free, no card)

Chosen for #47 as the free path: Render hosts the app (free web service,
spins down after ~15 min idle, wakes on the next request), Supabase hosts
Postgres (free tier, pgvector supported). This requires creating accounts
on both — that step is the project owner's, not something an agent can do.
`render.yaml` in the repo root is a Render Blueprint that automates most
of the Render-side setup once you connect the repo.

### 1. Supabase — create the database

1. Sign up at supabase.com, create a new project (pick any region/name).
2. Wait for provisioning, then open **Project Settings → Database**.
   Under "Connection parameters" you'll find `Host`, `Database name`,
   `Port`, `User`, `Password` — these map directly onto this app's
   `POSTGRES_HOST` / `POSTGRES_DB` / `POSTGRES_PORT` / `POSTGRES_USER` /
   `POSTGRES_PASSWORD` env vars. Use the **connection pooler** host/port
   (labelled "Transaction" mode, usually port `6543`) rather than the
   direct connection — Render's free tier and Supabase's pooler work
   better together than a direct connection under load.
3. Open the **SQL Editor** and run `CREATE EXTENSION IF NOT EXISTS vector;`
   once, by hand — Supabase's `postgres` user has permission to do this,
   but it's simplest to do it up front rather than rely on Django's
   `pgvector_setup` migration having that permission on first run (it
   should also work automatically; running it manually first removes any
   doubt).

### 2. Render — deploy the app

1. Sign up at render.com, connect your GitHub account, and give Render
   access to the `signal_scholar` repo.
2. Create a new **Blueprint** (not a plain Web Service) and point it at
   this repo — Render reads `render.yaml` and creates the web service
   with the right build/start commands automatically.
3. Render will prompt for the env vars marked `sync: false` in
   `render.yaml` (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_HOST`, `POSTGRES_PORT`) — fill these in with the Supabase
   pooler values from step 1. `DJANGO_SECRET_KEY` is generated
   automatically by Render; `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, and
   `DB_SSLMODE` are already set correctly in `render.yaml`.
4. Deploy. The build command runs `migrate` as part of the build step, so
   the database schema is created automatically on first deploy.
5. Once live, verify: load the Render URL, try the search page and a
   paper detail page, and confirm static files (the search page's CSS-free
   but JS-dependent weight slider) load without console errors.
6. Record the live URL in `README.md` (the last unchecked box in #47).

### If something goes wrong

- **Static files 404 / manifest error**: confirm the build command's
  `collectstatic --noinput` step actually ran (check the Render build
  log) — `WHITENOISE_MANIFEST_STRICT = False` prevents a hard crash, but
  files won't be cache-busted correctly without it.
- **`relation "..." does not exist"`**: the build command's `migrate`
  step didn't run or failed — check the build log; a common cause is the
  Supabase connection details being wrong (wrong host/port/pooler mode).
- **`CREATE EXTENSION vector` permission error**: confirm you ran the SQL
  Editor step above; Supabase's default `postgres` role should have this
  permission, but some restricted-role setups don't.
