"""Tests for `papers.services.search_papers` (GitHub issue #16).

`search_papers` was extracted out of `papers.api`'s Ninja view (#15) so
it could be shared with the HTML search page (#16). These tests exercise
it directly, HTTP-agnostically -- no Django test `client`, no Ninja.
`tests/test_papers_search.py` already covers the same underlying query
behavior end to end through `/api/search`; these focus on the function's
own contract (the `ValueError`, the `limit` cap, and the exact dict
shape) rather than re-testing filter/order semantics already covered
there.
"""

from __future__ import annotations

import pytest

from papers.models import Paper
from papers.services import MAX_LIMIT, search_papers


@pytest.mark.django_db
def test_raises_value_error_on_blank_q():
    with pytest.raises(ValueError):
        search_papers("")


@pytest.mark.django_db
def test_raises_value_error_on_whitespace_only_q():
    with pytest.raises(ValueError):
        search_papers("   ")


@pytest.mark.django_db
def test_limit_above_max_is_capped():
    for i in range(3):
        Paper.objects.create(title=f"Astro paper {i}")

    results, count = search_papers("astro", limit=500)

    assert count == 3
    assert len(results) == 3


@pytest.mark.django_db
def test_limit_capped_actually_truncates_when_matches_exceed_max():
    for i in range(MAX_LIMIT + 5):
        Paper.objects.create(title=f"Cosmology paper {i}")

    results, count = search_papers("cosmology", limit=500)

    assert count == MAX_LIMIT + 5
    assert len(results) == MAX_LIMIT


@pytest.mark.django_db
def test_results_are_plain_dicts_with_exactly_nine_expected_keys():
    Paper.objects.create(title="Quantum computing basics")

    results, count = search_papers("quantum")

    assert count == 1
    assert isinstance(results[0], dict)
    assert set(results[0].keys()) == {
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
