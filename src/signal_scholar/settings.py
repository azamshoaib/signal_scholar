"""Django settings for the signal_scholar project.

This is intentionally minimal scaffolding (see GitHub issue #1). Postgres
is configured for local development in GitHub issue #2 (see DATABASES
below); installed apps for domain models and the API layer are handled in
follow-up issues.
"""

import os
from pathlib import Path

# src/signal_scholar/settings.py -> repo root is three parents up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


# SECURITY WARNING: the "django-insecure-..." fallback below is a
# LOCAL-DEV-ONLY value. It must never be used where DEBUG=False -- any
# real deployment must set DJANGO_SECRET_KEY to a long, random value.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")

# Defaults to True (unchanged from before) so local dev stays zero-config
# without a .env file. Any real deployment must explicitly set
# DJANGO_DEBUG=False -- `manage.py check --deploy` is the safety net that
# catches a forgotten override (security.W018).
DEBUG = _env_bool("DJANGO_DEBUG", True)

# Comma-separated list of allowed hosts, e.g. "example.com,www.example.com".
# Defaults to [] when unset (unchanged from today -- Django already permits
# localhost/127.0.0.1 automatically while DEBUG=True). A real deployment
# must set DJANGO_ALLOWED_HOSTS to its actual domain(s).
_allowed_hosts_env = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS: list[str] = [
    host.strip() for host in _allowed_hosts_env.split(",") if host.strip()
]

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pgvector_setup",
    "papers",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "signal_scholar.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "src" / "signal_scholar" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "signal_scholar"),
        "USER": os.environ.get("POSTGRES_USER", "signal_scholar"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "signal_scholar_dev_password"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Without this, {% static %} raises a hard 500 for any file not yet in the
# manifest (e.g. `collectstatic` hasn't been run -- the common case for
# local dev/test, which use Django's dev static file serving instead).
# Falls back to the unhashed filename in that case; once a real deployment
# runs `collectstatic`, every referenced file has a manifest entry and this
# has no effect.
WHITENOISE_MANIFEST_STRICT = False

# Per GitHub issue #42: a public-facing login flow (mounted in
# signal_scholar/urls.py at /login/ and /logout/) so an unauthenticated
# visitor to an auth-gated page is redirected to /login/ instead of
# erroring, and a freshly-logged-in user lands somewhere that exists today.
LOGIN_URL = "login"
# Per GitHub issue #27 (#42 explicitly left this as "#27's call"): a
# freshly-logged-in user lands on their personalized feed rather than the
# placeholder `home` view.
LOGIN_REDIRECT_URL = "papers:feed"
# A logged-out user should not be sent to a login-gated page, so this
# stays "home", unlike LOGIN_REDIRECT_URL above.
LOGOUT_REDIRECT_URL = "home"
