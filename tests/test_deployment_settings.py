"""Tests for the deployment-readiness settings added in GitHub issue #29.

`SECRET_KEY`, `DEBUG`, and `ALLOWED_HOSTS` in `signal_scholar/settings.py`
are read from environment variables (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`,
`DJANGO_ALLOWED_HOSTS`) with dev-friendly defaults. Since these are
module-level assignments evaluated at import time, we reload the settings
module under monkeypatched environment variables to exercise each branch.
"""

from __future__ import annotations

import importlib

import pytest

from signal_scholar import settings as settings_module


@pytest.fixture
def reload_settings(monkeypatch):
    """Reload signal_scholar.settings after the caller tweaks env vars.

    Restores the original module state afterwards so later tests (and
    pytest-django's use of the real settings) aren't affected.
    """

    def _reload():
        return importlib.reload(settings_module)

    yield _reload
    importlib.reload(settings_module)


def test_secret_key_defaults_to_dev_only_fallback(monkeypatch, reload_settings):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)

    reloaded = reload_settings()

    assert reloaded.SECRET_KEY == "django-insecure-dev-only-change-me"


def test_secret_key_reads_from_env(monkeypatch, reload_settings):
    monkeypatch.setenv("DJANGO_SECRET_KEY", "a-real-production-secret")

    reloaded = reload_settings()

    assert reloaded.SECRET_KEY == "a-real-production-secret"


def test_debug_defaults_to_true_when_unset(monkeypatch, reload_settings):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)

    reloaded = reload_settings()

    assert reloaded.DEBUG is True


@pytest.mark.parametrize("value", ["False", "false", "0", "no", "off"])
def test_debug_env_var_can_disable_debug(monkeypatch, reload_settings, value):
    monkeypatch.setenv("DJANGO_DEBUG", value)

    reloaded = reload_settings()

    assert reloaded.DEBUG is False


@pytest.mark.parametrize("value", ["True", "true", "1", "yes", "on"])
def test_debug_env_var_can_enable_debug(monkeypatch, reload_settings, value):
    monkeypatch.setenv("DJANGO_DEBUG", value)

    reloaded = reload_settings()

    assert reloaded.DEBUG is True


def test_allowed_hosts_defaults_to_empty_list_when_unset(monkeypatch, reload_settings):
    monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)

    reloaded = reload_settings()

    assert reloaded.ALLOWED_HOSTS == []


def test_allowed_hosts_parses_comma_separated_env_var(monkeypatch, reload_settings):
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com, www.example.com,api.example.com")

    reloaded = reload_settings()

    assert reloaded.ALLOWED_HOSTS == ["example.com", "www.example.com", "api.example.com"]


def test_static_root_and_whitenoise_storage_are_configured():
    assert settings_module.STATIC_ROOT == settings_module.BASE_DIR / "staticfiles"
    assert (
        settings_module.STORAGES["staticfiles"]["BACKEND"]
        == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )


def test_whitenoise_middleware_directly_after_security_middleware():
    security_index = settings_module.MIDDLEWARE.index(
        "django.middleware.security.SecurityMiddleware"
    )
    whitenoise_index = settings_module.MIDDLEWARE.index(
        "whitenoise.middleware.WhiteNoiseMiddleware"
    )

    assert whitenoise_index == security_index + 1


def test_xframe_options_middleware_is_installed():
    assert (
        "django.middleware.clickjacking.XFrameOptionsMiddleware"
        in settings_module.MIDDLEWARE
    )


def test_wsgi_module_exposes_application_callable():
    from signal_scholar.wsgi import application

    assert callable(application)
