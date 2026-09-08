"""Session-wide test setup shared across the whole suite."""

from unittest.mock import patch

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


@pytest.fixture(autouse=True)
def _no_live_openalex_search_by_default():
    """Mock `papers.services.search_works` to return no results by default.

    `search_papers_with_live_fallback` (the search-page/API's live
    OpenAlex fallback for a zero-local-results query) calls this on
    every zero-result search unless it's mocked -- without this fixture,
    every existing zero-result test (there are several: "no matching
    papers", "zero results renders no weight slider", etc.) would make a
    real network call to OpenAlex on every test run, breaking this
    project's "no live network calls in the test suite" convention
    (established since #8) and making the suite slow/flaky/non-
    deterministic.

    Tests that want to exercise the live-fallback behavior itself should
    request this fixture directly and set `.return_value`/`.side_effect`
    on the yielded mock, mirroring how other tests patch a client
    function at its import site in the calling module.
    """
    with patch("papers.services.search_works", return_value=[]) as mock:
        yield mock
