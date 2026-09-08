"""Tests for the follow/unfollow endpoints (GitHub issue #25).

Uses Django's test `client` fixture (pytest-django) against the real
Ninja-mounted endpoints in `papers/api.py`. Authentication goes through
the real session-cookie login (`client.login(...)`, matching #42's own
test pattern) since Ninja's `django_auth` checks
`request.user.is_authenticated` off the standard Django session -- no
mocking of auth involved.

Both endpoint pairs (`/api/authors/{id}/follow` and
`/api/institutions/{id}/follow`) are exercised for every case: follow
(new row), follow (duplicate -> idempotent), unfollow (existing row),
unfollow (never-followed -> idempotent), unauthenticated (401), and a
nonexistent target (404) -- per issue #25's acceptance criteria.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Follow, Institution

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="s3cret-pw!")


@pytest.fixture
def author():
    return Author.objects.create(name="Ada Lovelace")


@pytest.fixture
def institution():
    return Institution.objects.create(name="Aalto University")


# --- Author endpoints --------------------------------------------------


def test_follow_author_new_creates_row_and_returns_201(client, user, author):
    client.login(username="alice", password="s3cret-pw!")

    response = client.post(f"/api/authors/{author.id}/follow")

    assert response.status_code == 201
    assert response.json() == {"following": True, "created": True}
    assert Follow.objects.filter(user=user, author=author).count() == 1


def test_follow_author_duplicate_is_idempotent_returns_200_no_dup_row(
    client, user, author
):
    client.login(username="alice", password="s3cret-pw!")
    client.post(f"/api/authors/{author.id}/follow")

    response = client.post(f"/api/authors/{author.id}/follow")

    assert response.status_code == 200
    assert response.json() == {"following": True, "created": False}
    assert Follow.objects.filter(user=user, author=author).count() == 1


def test_unfollow_author_existing_deletes_row_and_returns_204(client, user, author):
    client.login(username="alice", password="s3cret-pw!")
    client.post(f"/api/authors/{author.id}/follow")

    response = client.delete(f"/api/authors/{author.id}/follow")

    assert response.status_code == 204
    assert not Follow.objects.filter(user=user, author=author).exists()


def test_unfollow_author_never_followed_is_idempotent_204(client, user, author):
    client.login(username="alice", password="s3cret-pw!")

    response = client.delete(f"/api/authors/{author.id}/follow")

    assert response.status_code == 204
    assert not Follow.objects.filter(user=user, author=author).exists()


def test_follow_author_unauthenticated_returns_401(client, author):
    response = client.post(f"/api/authors/{author.id}/follow")

    assert response.status_code == 401


def test_unfollow_author_unauthenticated_returns_401(client, author):
    response = client.delete(f"/api/authors/{author.id}/follow")

    assert response.status_code == 401


def test_follow_nonexistent_author_returns_404(client, user):
    client.login(username="alice", password="s3cret-pw!")

    response = client.post("/api/authors/999999/follow")

    assert response.status_code == 404


def test_unfollow_nonexistent_author_returns_404(client, user):
    client.login(username="alice", password="s3cret-pw!")

    response = client.delete("/api/authors/999999/follow")

    assert response.status_code == 404


# --- Institution endpoints ----------------------------------------------


def test_follow_institution_new_creates_row_and_returns_201(client, user, institution):
    client.login(username="alice", password="s3cret-pw!")

    response = client.post(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 201
    assert response.json() == {"following": True, "created": True}
    assert Follow.objects.filter(user=user, institution=institution).count() == 1


def test_follow_institution_duplicate_is_idempotent_returns_200_no_dup_row(
    client, user, institution
):
    client.login(username="alice", password="s3cret-pw!")
    client.post(f"/api/institutions/{institution.id}/follow")

    response = client.post(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 200
    assert response.json() == {"following": True, "created": False}
    assert Follow.objects.filter(user=user, institution=institution).count() == 1


def test_unfollow_institution_existing_deletes_row_and_returns_204(
    client, user, institution
):
    client.login(username="alice", password="s3cret-pw!")
    client.post(f"/api/institutions/{institution.id}/follow")

    response = client.delete(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 204
    assert not Follow.objects.filter(user=user, institution=institution).exists()


def test_unfollow_institution_never_followed_is_idempotent_204(
    client, user, institution
):
    client.login(username="alice", password="s3cret-pw!")

    response = client.delete(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 204
    assert not Follow.objects.filter(user=user, institution=institution).exists()


def test_follow_institution_unauthenticated_returns_401(client, institution):
    response = client.post(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 401


def test_unfollow_institution_unauthenticated_returns_401(client, institution):
    response = client.delete(f"/api/institutions/{institution.id}/follow")

    assert response.status_code == 401


def test_follow_nonexistent_institution_returns_404(client, user):
    client.login(username="alice", password="s3cret-pw!")

    response = client.post("/api/institutions/999999/follow")

    assert response.status_code == 404


def test_unfollow_nonexistent_institution_returns_404(client, user):
    client.login(username="alice", password="s3cret-pw!")

    response = client.delete("/api/institutions/999999/follow")

    assert response.status_code == 404
