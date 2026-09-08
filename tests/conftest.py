"""Session-wide test setup shared across the whole suite."""

import pytest
from django.core.management import call_command


@pytest.fixture(scope="session", autouse=True)
def _collectstatic_for_whitenoise_manifest():
    """Populate STATIC_ROOT before any test renders a `{% static %}` tag.

    Per GitHub issue #29, `STORAGES["staticfiles"]` is whitenoise's
    `CompressedManifestStaticFilesStorage`, which resolves `{% static %}`
    URLs from a manifest built by `collectstatic`. Without that manifest
    (e.g. a fresh checkout that hasn't run `collectstatic` yet), Django
    raises instead of rendering the page -- `WHITENOISE_MANIFEST_STRICT =
    False` only skips the manifest *lookup*, it doesn't remove the
    requirement that the file exist under STATIC_ROOT. Running
    `collectstatic` once per test session keeps `pytest` runnable
    out of the box, matching production, where a real deploy always runs
    `collectstatic` before starting the app.
    """
    call_command("collectstatic", verbosity=0, interactive=False)
