"""Django settings for the signal_scholar project.

This is intentionally minimal scaffolding (see GitHub issue #1). Database
configuration beyond the default SQLite, installed apps for domain models,
and the API layer are handled in follow-up issues.
"""

from pathlib import Path

# src/signal_scholar/settings.py -> repo root is three parents up.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# SECURITY WARNING: keep this only for local/dev use until a real secret
# management story lands.
SECRET_KEY = "django-insecure-dev-only-change-me"

DEBUG = True

ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS: list[str] = []

MIDDLEWARE: list[str] = []

ROOT_URLCONF = "signal_scholar.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"
