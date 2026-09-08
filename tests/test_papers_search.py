"""Tests for `GET /api/search` (GitHub issue #15).

Uses Django's test `client` fixture (from pytest-django) to hit the real
Ninja-mounted endpoint end to end, and hand-constructed `Paper`/`Author`/
`Venue`/`PaperAuthorship` fixtures -- no live OpenAlex calls.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Paper, PaperAuthorship, Venue


@pytest.mark.django_db
def test_results_sorted_by_combined_score_descending_with_deterministic_tiebreak(client):
    # Two papers share the same combined_score (0.0, the model default) so
    # the `id` tiebreaker is what actually determines their relative order
    # below; the third paper's higher combined_score must sort first.
    low_a = Paper.objects.create(title="Deep learning for X", combined_score=0.0)
    low_b = Paper.objects.create(title="Deep learning for Y", combined_score=0.0)
    high = Paper.objects.create(title="Deep learning breakthrough", combined_score=99.0)

    response = client.get("/api/search", {"q": "deep learning"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    ids_in_order = [r["id"] for r in data["results"]]
    assert ids_in_order == [high.id, low_a.id, low_b.id]


@pytest.mark.django_db
def test_query_matches_via_abstract_only(client):
    paper = Paper.objects.create(
        title="Completely unrelated title",
        abstract="This paper discusses quantum entanglement in detail.",
    )
    Paper.objects.create(title="Another paper", abstract="Nothing relevant here.")

    response = client.get("/api/search", {"q": "entanglement"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["id"] == paper.id


@pytest.mark.django_db
def test_query_matches_via_title_case_insensitive(client):
    paper = Paper.objects.create(title="Graph Neural Networks for Molecules")

    response = client.get("/api/search", {"q": "GRAPH neural"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["id"] == paper.id


@pytest.mark.django_db
def test_no_matching_papers_returns_empty_results_http_200(client):
    Paper.objects.create(title="Something about biology")

    response = client.get("/api/search", {"q": "nonexistent-xyz-term"})

    assert response.status_code == 200
    assert response.json() == {"results": [], "count": 0}


@pytest.mark.django_db
def test_missing_q_returns_422(client):
    response = client.get("/api/search")

    assert response.status_code == 422


@pytest.mark.django_db
def test_blank_q_returns_400(client):
    response = client.get("/api/search", {"q": "   "})

    assert response.status_code == 400


@pytest.mark.django_db
def test_empty_string_q_returns_400(client):
    response = client.get("/api/search", {"q": ""})

    assert response.status_code == 400


@pytest.mark.django_db
def test_paper_with_zero_authorships_has_null_first_author_name(client):
    paper = Paper.objects.create(title="Solo unclaimed paper about robotics")

    response = client.get("/api/search", {"q": "robotics"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["id"] == paper.id
    assert data["results"][0]["first_author_name"] is None


@pytest.mark.django_db
def test_limit_truncates_results_but_count_reflects_total(client):
    for i in range(5):
        Paper.objects.create(title=f"Robotics paper {i}", combined_score=float(i))

    response = client.get("/api/search", {"q": "robotics", "limit": 2})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 5
    assert len(data["results"]) == 2


@pytest.mark.django_db
def test_limit_above_100_is_silently_capped_not_rejected(client):
    for i in range(3):
        Paper.objects.create(title=f"Astro paper {i}")

    response = client.get("/api/search", {"q": "astro", "limit": 500})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["results"]) == 3


@pytest.mark.django_db
def test_limit_zero_or_negative_returns_422(client):
    Paper.objects.create(title="Astro paper")

    response_zero = client.get("/api/search", {"q": "astro", "limit": 0})
    response_negative = client.get("/api/search", {"q": "astro", "limit": -1})

    assert response_zero.status_code == 422
    assert response_negative.status_code == 422


@pytest.mark.django_db
def test_default_limit_is_25(client):
    for i in range(30):
        Paper.objects.create(title=f"Chemistry paper {i}")

    response = client.get("/api/search", {"q": "chemistry"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 30
    assert len(data["results"]) == 25


@pytest.mark.django_db
def test_q_does_not_match_author_names(client):
    author = Author.objects.create(name="Smith")
    paper = Paper.objects.create(title="A paper with nothing matching in it")
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/api/search", {"q": "Smith"})

    assert response.status_code == 200
    assert response.json() == {"results": [], "count": 0}


@pytest.mark.django_db
def test_response_shape_has_exactly_expected_fields(client):
    venue = Venue.objects.create(name="NeurIPS")
    author = Author.objects.create(name="Ada Lovelace")
    paper = Paper.objects.create(
        title="Analytical engines and computation",
        publication_year=2020,
        doi="10.1234/abc",
        abstract="On analytical engines.",
        venue=venue,
        citation_velocity=1.5,
        author_reputation_score=42.0,
        velocity_score=17.0,
        combined_score=29.5,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/api/search", {"q": "analytical"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    result = data["results"][0]
    assert set(result.keys()) == {
        "id",
        "title",
        "publication_year",
        "doi",
        "venue_name",
        "first_author_name",
        "citation_velocity",
        "author_reputation_score",
        "velocity_score",
        "combined_score",
    }
    assert result == {
        "id": paper.id,
        "title": "Analytical engines and computation",
        "publication_year": 2020,
        "doi": "10.1234/abc",
        "venue_name": "NeurIPS",
        "first_author_name": "Ada Lovelace",
        "citation_velocity": 1.5,
        "author_reputation_score": 42.0,
        "velocity_score": 17.0,
        "combined_score": 29.5,
    }


@pytest.mark.django_db
def test_health_endpoint_still_works_after_mounting_papers_router(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _build_matching_papers(*, num_papers: int) -> None:
    venue = Venue.objects.create(name="Venue A")
    for i in range(num_papers):
        author = Author.objects.create(name=f"Author {i}")
        paper = Paper.objects.create(title=f"Matching paper {i}", venue=venue)
        PaperAuthorship.objects.create(paper=paper, author=author, position=1)


# 1 COUNT query + 1 main SELECT (with select_related join, no extra
# query) + 2 prefetch queries for authorships__author (one for
# authorships, one for their authors) -- a fixed cost regardless of how
# many matching papers there are, not one extra query per paper (which
# would be the N+1 bug #14 already had to fix once, guarded against
# here).
EXPECTED_SEARCH_QUERY_COUNT = 4


@pytest.mark.django_db
def test_no_n_plus_one_query_growth_small_fixture(django_assert_num_queries, client):
    _build_matching_papers(num_papers=3)

    with django_assert_num_queries(EXPECTED_SEARCH_QUERY_COUNT):
        client.get("/api/search", {"q": "matching"})


@pytest.mark.django_db
def test_no_n_plus_one_query_growth_larger_fixture_same_query_count(
    django_assert_num_queries, client
):
    # 10x the papers of the small fixture above -- if the endpoint had a
    # real N+1 (e.g. one extra query per paper from re-querying
    # authorships instead of reusing the prefetch cache), this would blow
    # past the fixed count the small fixture also satisfies.
    _build_matching_papers(num_papers=30)

    with django_assert_num_queries(EXPECTED_SEARCH_QUERY_COUNT):
        client.get("/api/search", {"q": "matching"})
