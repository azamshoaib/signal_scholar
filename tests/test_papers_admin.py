"""Automated coverage for the Django admin registrations (GitHub issue #7).

Per the issue's Acceptance criteria, "verifying it works" is an automated
check, not a manual QA step: create a superuser programmatically and use
Django's test client to assert HTTP 200 for `/admin/` itself, plus the
changelist/add-form/change-form URLs for each of the five registered
models (`Paper`, `Author`, `Institution`, `Venue`, `Citation`).
`PaperAuthorship` is intentionally excluded — it's a `TabularInline` on
`PaperAdmin`, not a standalone registration (see `src/papers/admin.py`).
"""

import pytest
from django.urls import reverse

from papers.models import Author, Citation, Institution, Paper, Venue

MODELS_UNDER_TEST = ["paper", "author", "institution", "venue", "citation"]


# `admin_client` below is pytest-django's built-in fixture: it creates a
# superuser programmatically (via `django_user_model.objects.create_superuser`)
# and returns a Django test client already logged in as that user.


@pytest.fixture
def one_row_per_model(db):
    institution = Institution.objects.create(name="Aalto University")
    author = Author.objects.create(name="Ada Lovelace", institution=institution)
    venue = Venue.objects.create(name="NeurIPS")
    paper_a = Paper.objects.create(title="Paper A", venue=venue)
    paper_b = Paper.objects.create(title="Paper B")
    citation = Citation.objects.create(citing_paper=paper_a, cited_paper=paper_b)

    return {
        "institution": institution,
        "author": author,
        "venue": venue,
        "paper": paper_a,
        "citation": citation,
    }


@pytest.mark.django_db
def test_admin_index_returns_200(admin_client):
    response = admin_client.get(reverse("admin:index"))

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", MODELS_UNDER_TEST)
def test_admin_changelist_returns_200(admin_client, model_name):
    url = reverse(f"admin:papers_{model_name}_changelist")

    response = admin_client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", MODELS_UNDER_TEST)
def test_admin_add_form_returns_200(admin_client, model_name):
    url = reverse(f"admin:papers_{model_name}_add")

    response = admin_client.get(url)

    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("model_name", MODELS_UNDER_TEST)
def test_admin_change_form_returns_200(admin_client, one_row_per_model, model_name):
    instance = one_row_per_model[model_name]
    url = reverse(f"admin:papers_{model_name}_change", args=[instance.pk])

    response = admin_client.get(url)

    assert response.status_code == 200
