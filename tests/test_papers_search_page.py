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
    # The weight_slider.js <script> tag is page chrome (loaded once in
    # search.html, outside #results), not part of the swapped partial.
    assert "weight_slider.js" not in body


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


# --- GitHub issue #18: year_min / year_max / velocity_min filters ---


@pytest.mark.django_db
def test_year_min_alone_excludes_older_paper(client):
    Paper.objects.create(title="Robotics old paper", publication_year=2010)
    Paper.objects.create(title="Robotics new paper", publication_year=2020)

    response = client.get("/search/", {"q": "robotics", "year_min": 2015})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics new paper" in body
    assert "Robotics old paper" not in body


@pytest.mark.django_db
def test_year_max_alone_excludes_newer_paper(client):
    Paper.objects.create(title="Robotics old paper", publication_year=2010)
    Paper.objects.create(title="Robotics new paper", publication_year=2020)

    response = client.get("/search/", {"q": "robotics", "year_max": 2015})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics old paper" in body
    assert "Robotics new paper" not in body


@pytest.mark.django_db
def test_year_min_and_year_max_combined(client):
    Paper.objects.create(title="Robotics ancient paper", publication_year=2000)
    Paper.objects.create(title="Robotics mid paper", publication_year=2015)
    Paper.objects.create(title="Robotics future paper", publication_year=2030)

    response = client.get(
        "/search/", {"q": "robotics", "year_min": 2010, "year_max": 2020}
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics mid paper" in body
    assert "Robotics ancient paper" not in body
    assert "Robotics future paper" not in body


@pytest.mark.django_db
def test_velocity_min_alone_excludes_low_velocity_paper(client):
    Paper.objects.create(title="Robotics low velocity", citation_velocity=1.0)
    Paper.objects.create(title="Robotics high velocity", citation_velocity=10.0)

    response = client.get("/search/", {"q": "robotics", "velocity_min": 5.0})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics high velocity" in body
    assert "Robotics low velocity" not in body


@pytest.mark.django_db
def test_filters_combine_with_q_and_semantics(client):
    Paper.objects.create(
        title="Robotics breakthrough", publication_year=2020, citation_velocity=10.0
    )
    Paper.objects.create(
        title="Robotics old breakthrough", publication_year=2000, citation_velocity=10.0
    )

    response = client.get(
        "/search/", {"q": "robotics", "year_min": 2010, "velocity_min": 5.0}
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics breakthrough" in body
    assert "Robotics old breakthrough" not in body


@pytest.mark.django_db
def test_null_publication_year_excluded_when_year_filter_active(client):
    Paper.objects.create(title="Robotics unknown year paper", publication_year=None)
    Paper.objects.create(title="Robotics dated paper", publication_year=2020)

    response = client.get("/search/", {"q": "robotics", "year_min": 2000})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics dated paper" in body
    assert "Robotics unknown year paper" not in body


@pytest.mark.django_db
def test_year_min_greater_than_year_max_shows_error_not_results(client):
    Paper.objects.create(title="Robotics paper", publication_year=2020)

    response = client.get(
        "/search/", {"q": "robotics", "year_min": 2020, "year_max": 2010}
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "year_min must not be greater than year_max" in body
    assert "Robotics paper" not in body


@pytest.mark.django_db
def test_blank_q_with_filters_present_still_shows_prompt_text(client):
    response = client.get(
        "/search/",
        {"q": "   ", "year_min": 2010, "year_max": 2020, "velocity_min": 1.0},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Enter a topic to search." in body


@pytest.mark.django_db
def test_malformed_filter_value_silently_ignored_not_an_error(client):
    paper = Paper.objects.create(title="Robotics paper", publication_year=2020)

    response = client.get(
        "/search/", {"q": "robotics", "year_min": "not-a-number"}
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics paper" in body
    assert paper.id  # sanity: fixture matched, no error text shown
    assert "must not be" not in body


@pytest.mark.django_db
def test_filter_values_round_trip_into_form_inputs(client):
    Paper.objects.create(title="Robotics paper", publication_year=2020)

    response = client.get(
        "/search/",
        {"q": "robotics", "year_min": 2015, "year_max": 2025, "velocity_min": 2.5},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="year_min" name="year_min" value="2015"' in body
    assert 'id="year_max" name="year_max" value="2025"' in body
    assert 'id="velocity_min" name="velocity_min" min="0" step="any" value="2.5"' in body


@pytest.mark.django_db
def test_omitted_filter_values_round_trip_as_empty_not_none(client):
    Paper.objects.create(title="Robotics paper", publication_year=2020)

    response = client.get("/search/", {"q": "robotics", "year_min": 2015})
    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="year_min" name="year_min" value="2015"' in body
    assert 'id="year_max" name="year_max" value=""' in body
    assert 'id="velocity_min" name="velocity_min" min="0" step="any" value=""' in body
    assert 'value="None"' not in body


@pytest.mark.django_db
def test_omitting_all_filters_reproduces_prior_behavior(client):
    Paper.objects.create(title="Robotics paper", publication_year=2020)

    response = client.get("/search/", {"q": "robotics"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "Robotics paper" in body
    assert "Showing 1 of 1 results." in body


# --- GitHub issue #19: adjustable-weights slider to re-sort results ---


@pytest.mark.django_db
def test_matching_query_renders_weight_slider_and_row_data_attributes(client):
    venue = Venue.objects.create(name="NeurIPS")
    author = Author.objects.create(name="Ada Lovelace", h_index_normalized=2.0)
    paper = Paper.objects.create(
        title="Analytical engines and computation",
        publication_year=2020,
        venue=venue,
        author_reputation_score=40.0,
        velocity_score=20.0,
        combined_score=30.0,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/search/", {"q": "analytical"})
    body = response.content.decode()

    assert response.status_code == 200
    # Default weight matches #13's current DEFAULT_REPUTATION_WEIGHT (0.5
    # -> 50), not a hardcoded literal in the template.
    assert 'id="weight-slider"' in body
    assert 'value="50"' in body
    assert "50% reputation / 50% velocity" in body
    assert f'data-paper-id="{paper.id}"' in body
    assert 'data-reputation-score="40.0000"' in body
    assert 'data-velocity-score="20.0000"' in body


@pytest.mark.django_db
def test_zero_results_renders_no_weight_slider(client):
    Paper.objects.create(title="Something about biology")

    response = client.get("/search/", {"q": "nonexistent-xyz-term"})
    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="weight-slider"' not in body


@pytest.mark.django_db
def test_no_query_renders_no_weight_slider(client):
    response = client.get("/search/")
    body = response.content.decode()

    assert response.status_code == 200
    assert 'id="weight-slider"' not in body


@pytest.mark.django_db
def test_full_page_request_includes_weight_slider_script_tag(client):
    response = client.get("/search/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "weight_slider.js" in body
