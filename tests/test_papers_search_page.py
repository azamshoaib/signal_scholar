"""Tests for the `GET /search/` HTML search page (GitHub issue #16).

Uses Django's test `client` fixture (from pytest-django) to hit the real
page-view endpoint end to end, with hand-constructed `Paper`/`Author`/
`Venue`/`PaperAuthorship` fixtures -- no live OpenAlex calls, mirroring
`tests/test_papers_search.py`'s approach for the JSON API.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Paper, PaperAuthorship, Venue


@pytest.mark.django_db
def test_no_query_shows_prompt_text(client):
    response = client.get("/search/")

    assert response.status_code == 200
    assert "Enter a topic to search." in response.content.decode()


@pytest.mark.django_db
def test_blank_query_shows_prompt_text_not_error(client):
    response = client.get("/search/", {"q": "   "})

    assert response.status_code == 200
    assert "Enter a topic to search." in response.content.decode()


@pytest.mark.django_db
def test_matching_query_shows_fixture_paper_fields(client):
    venue = Venue.objects.create(name="NeurIPS")
    author = Author.objects.create(name="Ada Lovelace")
    paper = Paper.objects.create(
        title="Analytical engines and computation",
        publication_year=2020,
        venue=venue,
        combined_score=29.456,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/search/", {"q": "analytical"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Analytical engines and computation" in body
    assert "Ada Lovelace" in body
    assert "NeurIPS" in body
    assert "2020" in body
    # combined_score rounded to 1 decimal place, labeled "Score".
    assert "Score: 29.5" in body
    # The search box's value reflects the submitted q.
    assert 'value="analytical"' in body
    assert "Showing 1 of 1 results." in body


@pytest.mark.django_db
def test_non_matching_query_shows_zero_results_text(client):
    Paper.objects.create(title="Something about biology")

    response = client.get("/search/", {"q": "nonexistent-xyz-term"})
    body = response.content.decode()

    assert response.status_code == 200
    assert 'No papers found for "nonexistent-xyz-term". Try a different search term.' in body


@pytest.mark.django_db
def test_htmx_request_returns_only_partial_not_full_page_chrome(client):
    Paper.objects.create(title="Robotics and control systems")

    response = client.get("/search/", {"q": "robotics"}, HTTP_HX_REQUEST="true")
    body = response.content.decode()

    assert response.status_code == 200
    assert "<form" not in body
    assert "<html" not in body
    assert "Robotics and control systems" in body


@pytest.mark.django_db
def test_full_page_request_includes_form_chrome(client):
    response = client.get("/search/")
    body = response.content.decode()

    assert "<form" in body
    assert "<html" in body


@pytest.mark.django_db
def test_results_ordered_by_combined_score_desc_then_id(client):
    low_a = Paper.objects.create(title="Deep learning for X", combined_score=0.0)
    low_b = Paper.objects.create(title="Deep learning for Y", combined_score=0.0)
    high = Paper.objects.create(title="Deep learning breakthrough", combined_score=99.0)

    response = client.get("/search/", {"q": "deep learning"})
    body = response.content.decode()

    first_pos = body.index("Deep learning breakthrough")
    second_pos = body.index("Deep learning for X")
    third_pos = body.index("Deep learning for Y")

    assert first_pos < second_pos < third_pos
    assert high.id and low_a.id and low_b.id  # fixtures created, order asserted above


@pytest.mark.django_db
def test_summary_line_reflects_truncation_at_default_limit(client):
    for i in range(30):
        Paper.objects.create(title=f"Chemistry paper {i}")

    response = client.get("/search/", {"q": "chemistry"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Showing 25 of 30 results." in body
