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

# SECURITY WARNING: keep this only for local/dev use until a real secret
# management story lands.
SECRET_KEY = "django-insecure-dev-only-change-me"

DEBUG = True

ALLOWED_HOSTS: list[str] = []

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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
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

# Per GitHub issue #42: a public-facing login flow (mounted in
# signal_scholar/urls.py at /login/ and /logout/) so an unauthenticated
# visitor to an auth-gated page is redirected to /login/ instead of
# erroring, and a freshly-logged-in user lands somewhere that exists today.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"
