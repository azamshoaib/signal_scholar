"""Tests for the public-facing login/logout flow (GitHub issue #42).

Per the issue, this establishes the first non-admin login path in the
project -- a shared prerequisite for #25's follow/unfollow endpoints and
#27's personalized feed page. Coverage here:

- `GET /login/` renders a minimal username/password form with a CSRF
  token.
- Logging in through the real `LoginView` (posting the form via the
  Django test client, per the issue's own acceptance criterion) produces
  a session that a later request recognizes as authenticated.
- Bad credentials re-render the form with an inline error, not a
  redirect.
- `POST /logout/` clears the session.
- An unauthenticated request to an auth-gated page redirects to
  `/login/` (via `LOGIN_URL`), not a raw 403/500.

`_protected_view` below is a throwaway, test-only `@login_required` view
wired into the *real* `signal_scholar.urls` urlpatterns for the duration
of a test (via the `protected_url` fixture) -- the project itself has no
auth-gated page yet (that's #25/#27's job), so this is the trivial stand-in
the issue's own notes call for to prove `LOGIN_URL` redirect behavior.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.urls import clear_url_caches, path, reverse

from signal_scholar import urls as project_urls


@login_required
def _protected_view(request):
    return HttpResponse(f"authenticated as {request.user.get_username()}")


@pytest.fixture
def protected_url():
    """Temporarily mount a `@login_required` view on the real urlconf."""
    entry = path("__test-protected__/", _protected_view, name="test-protected")
    project_urls.urlpatterns.append(entry)
    clear_url_caches()
    try:
        yield "/__test-protected__/"
    finally:
        project_urls.urlpatterns.remove(entry)
        clear_url_caches()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="s3cret-pw!")


@pytest.mark.django_db
def test_login_page_renders_username_password_form(client):
    response = client.get("/login/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "<form" in body
    assert "csrfmiddlewaretoken" in body
    assert 'name="username"' in body
    assert 'name="password"' in body


@pytest.mark.django_db
def test_login_with_valid_credentials_authenticates_session(client, user, protected_url):
    response = client.post(
        "/login/", {"username": "alice", "password": "s3cret-pw!"}
    )

    # LOGIN_REDIRECT_URL is "home", the existing root view.
    assert response.status_code == 302
    assert response.url == reverse("home")

    # The session produced by the real login view is recognized by an
    # auth-gated view: request.user.is_authenticated is true.
    protected_response = client.get(protected_url)
    assert protected_response.status_code == 200
    assert protected_response.content.decode() == "authenticated as alice"


@pytest.mark.django_db
def test_login_with_invalid_credentials_shows_inline_error(client, user):
    response = client.post(
        "/login/", {"username": "alice", "password": "wrong-password"}
    )
    body = response.content.decode()

    # Re-renders the form (no redirect) with an inline error.
    assert response.status_code == 200
    assert "didn't match" in body
    assert response.wsgi_request.user.is_authenticated is False


@pytest.mark.django_db
def test_logout_clears_session_and_redirects_sanely(client, user, protected_url):
    client.post("/login/", {"username": "alice", "password": "s3cret-pw!"})
    assert client.get(protected_url).status_code == 200

    response = client.post("/logout/")

    assert response.status_code == 302
    assert response.url == reverse("home")

    # The session no longer authenticates: the protected view now
    # redirects to /login/ instead of serving the page.
    after_logout = client.get(protected_url)
    assert after_logout.status_code == 302
    assert after_logout.url.startswith("/login/")


@pytest.mark.django_db
def test_unauthenticated_request_redirects_to_login_not_403_or_500(client, protected_url):
    response = client.get(protected_url)

    assert response.status_code == 302
    assert response.url == f"/login/?next={protected_url}"
