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
