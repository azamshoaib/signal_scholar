"""Tests for the `GET /papers/<id>/similar/` HTMX partial (GitHub issue
#24) and the "Find similar but better papers" button on `detail.html`.

Uses Django's test `client` fixture (from pytest-django) to hit the real
page-view endpoint end to end, with hand-constructed `Paper` fixtures --
no mocking, mirroring `tests/test_papers_detail_page.py`'s and
`tests/test_papers_similar.py`'s approaches.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Paper, PaperAuthorship, Venue


def _vec(*leading: float) -> list[float]:
    """Build a 768-dim vector: `leading` values, then zeros."""
    return list(leading) + [0.0] * (768 - len(leading))


@pytest.mark.django_db
def test_nonexistent_paper_returns_404(client):
    response = client.get("/papers/999999/similar/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_no_embedding_shows_message_at_200(client):
    paper = Paper.objects.create(title="Unembedded paper", embedding=None)

    response = client.get(f"/papers/{paper.id}/similar/")
    body = response.content.decode()

    assert response.status_code == 200
    assert (
        "This paper has no stored embedding yet, so it can't be compared "
        "for similarity." in body
    )


@pytest.mark.django_db
def test_embedding_present_but_no_candidates_shows_empty_message(client):
    paper = Paper.objects.create(
        title="Lonely embedded paper", embedding=_vec(1.0, 0.0)
    )

    response = client.get(f"/papers/{paper.id}/similar/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "No similar papers found." in body


@pytest.mark.django_db
def test_similar_candidate_renders_result_card(client):
    venue = Venue.objects.create(name="NeurIPS")
    author = Author.objects.create(name="Ada Lovelace")
    source = Paper.objects.create(title="Source paper", embedding=_vec(1.0, 0.0))
    candidate = Paper.objects.create(
        title="Candidate paper - close and good",
        embedding=_vec(0.99, 0.01),
        venue=venue,
        publication_year=2021,
        combined_score=42.345,
    )
    PaperAuthorship.objects.create(paper=candidate, author=author, position=1)

    response = client.get(f"/papers/{source.id}/similar/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Candidate paper - close and good" in body
    assert f'href="/papers/{candidate.id}/"' in body
    assert "Ada Lovelace" in body
    assert "NeurIPS" in body
    assert "2021" in body
    # combined_score rounded to 1 decimal place, labeled "Score".
    assert "Score: 42.3" in body
    # similarity_score rounded to 2 decimal places, labeled "Similarity",
    # not rescaled to 0-100.
    assert "Similarity:" in body
    # The source paper itself never appears among the results.
    assert "Source paper" not in body


@pytest.mark.django_db
def test_detail_page_always_renders_similar_button(client):
    with_embedding = Paper.objects.create(
        title="Paper with embedding", embedding=_vec(1.0, 0.0)
    )
    without_embedding = Paper.objects.create(
        title="Paper without embedding", embedding=None
    )

    for paper in (with_embedding, without_embedding):
        response = client.get(f"/papers/{paper.id}/")
        body = response.content.decode()

        assert response.status_code == 200
        assert "Find similar but better papers" in body
        assert f'hx-get="/papers/{paper.id}/similar/"' in body
        assert 'hx-target="#similar-results"' in body
        assert '<div id="similar-results"></div>' in body
