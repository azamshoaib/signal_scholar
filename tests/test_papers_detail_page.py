"""Tests for the `GET /papers/<id>/` HTML paper detail page (GitHub issue
#17).

Uses Django's test `client` fixture (from pytest-django) to hit the real
page-view endpoint end to end, with hand-constructed `Paper`/`Author`/
`Venue`/`PaperAuthorship` fixtures -- no live OpenAlex calls, mirroring
`tests/test_papers_search_page.py`'s approach.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Paper, PaperAuthorship, Venue


@pytest.mark.django_db
def test_nonexistent_paper_returns_404(client):
    response = client.get("/papers/999999/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_full_fixture_paper_renders_all_metadata(client):
    venue = Venue.objects.create(name="NeurIPS")
    paper = Paper.objects.create(
        title="Analytical engines and computation",
        publication_year=2020,
        venue=venue,
        doi="10.1145/xxxx",
        abstract="A study of analytical engines.",
    )
    first_author = Author.objects.create(name="Ada Lovelace")
    second_author = Author.objects.create(name="Charles Babbage")
    third_author = Author.objects.create(name="Alan Turing")
    PaperAuthorship.objects.create(paper=paper, author=third_author, position=3)
    PaperAuthorship.objects.create(paper=paper, author=first_author, position=1)
    PaperAuthorship.objects.create(paper=paper, author=second_author, position=2)

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Analytical engines and computation" in body
    assert "NeurIPS" in body
    assert "2020" in body
    assert 'href="https://doi.org/10.1145/xxxx"' in body
    assert "A study of analytical engines." in body

    # All 3 authors present, in position order.
    first_pos = body.index("Ada Lovelace")
    second_pos = body.index("Charles Babbage")
    third_pos = body.index("Alan Turing")
    assert first_pos < second_pos < third_pos


@pytest.mark.django_db
def test_missing_optional_fields_show_placeholders(client):
    paper = Paper.objects.create(
        title="A paper with missing metadata",
        publication_year=None,
        venue=None,
        doi=None,
        abstract=None,
    )

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Unknown" in body
    assert "No abstract available." in body
    assert "doi.org" not in body


@pytest.mark.django_db
def test_blank_abstract_shows_placeholder(client):
    paper = Paper.objects.create(
        title="A paper with a blank abstract",
        abstract="",
    )

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert "No abstract available." in body


@pytest.mark.django_db
def test_score_breakdown_shows_hand_computed_values(client):
    venue = Venue.objects.create(name="ICML")
    author = Author.objects.create(name="Grace Hopper", h_index_normalized=2.5)
    other_author = Author.objects.create(name="Margaret Hamilton")
    paper = Paper.objects.create(
        title="Compiler design principles",
        venue=venue,
        publication_year=2015,
        citation_velocity=25.0,
        influential_citation_ratio=0.4,
        author_reputation_score=50.0,  # 2.5 / 5.0 reference max * 100
        velocity_score=50.0,  # 25.0 / 50.0 reference max * 100
        influential_citation_score=40.0,  # min(0.4, 1.0) * 100
        combined_score=46.7,  # 0.34*50.0 + 0.33*50.0 + 0.33*40.0
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)
    PaperAuthorship.objects.create(paper=paper, author=other_author, position=2)

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert "Grace Hopper" in body
    # h_index_normalized rounded to 2 decimal places.
    assert "2.5" in body
    # author_reputation_score rounded to 1 decimal place.
    assert "50.0" in body
    # raw citation_velocity rounded to 2 decimal places.
    assert "25.0" in body
    # velocity_score rounded to 1 decimal place.
    assert "50.0" in body
    # raw influential_citation_ratio rounded to 2 decimal places.
    assert "0.4" in body
    # influential_citation_score rounded to 1 decimal place.
    assert "40.0" in body
    # combined_score rounded to 1 decimal place, shown prominently.
    assert "Combined score: 46.7" in body


@pytest.mark.django_db
def test_weight_sentence_reflects_default_constants(client):
    paper = Paper.objects.create(title="Any paper")

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert (
        "Combined score = 34% author reputation + 33% citation velocity "
        "+ 33% highly-influential-citation ratio." in body
    )


@pytest.mark.django_db
def test_unmatched_paper_renders_influential_citation_row_with_zero_fallback(client):
    # A paper never matched by Semantic Scholar (no DOI, or a DOI with no
    # Semantic Scholar record) renders the new row with
    # influential_citation_ratio == 0.0 / influential_citation_score ==
    # 0.0 -- the field's own defined default, not an error/"N/A".
    paper = Paper.objects.create(title="Never matched by Semantic Scholar", doi=None)

    response = client.get(f"/papers/{paper.id}/")

    assert response.status_code == 200
    assert paper.influential_citation_ratio == 0.0
    assert paper.influential_citation_score == 0.0


@pytest.mark.django_db
def test_zero_authorship_paper_renders_without_crashing(client):
    paper = Paper.objects.create(
        title="An orphan paper with no authors",
        author_reputation_score=0.0,
    )

    response = client.get(f"/papers/{paper.id}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "No authors on record" in body
    assert "0.0" in body


@pytest.mark.django_db
def test_search_results_link_to_detail_page(client):
    paper = Paper.objects.create(title="Robotics and control systems")

    response = client.get("/search/", {"q": "robotics"})
    body = response.content.decode()

    assert response.status_code == 200
    assert f'href="/papers/{paper.id}/"' in body
