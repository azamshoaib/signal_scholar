"""Tests for `papers.services.search_papers_with_live_fallback`.

`_no_live_openalex_search_by_default` (tests/conftest.py, autouse) mocks
`papers.services.search_works` to return `[]` for every test unless a
test overrides it -- these are the tests that override it, to actually
exercise the live-fallback path itself without a real network call.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openalex_client import OpenAlexAuthor, OpenAlexClientError, OpenAlexWork
from papers.models import Paper
from papers.services import search_papers, search_papers_with_live_fallback


def _work(openalex_id, title, cited_by_count=0):
    return OpenAlexWork(
        openalex_id=openalex_id,
        title=title,
        publication_year=2023,
        doi=None,
        abstract=None,
        venue=None,
        authors=[],
        cited_by_count=cited_by_count,
        counts_by_year=[],
    )


@pytest.mark.django_db
def test_local_hit_never_calls_openalex(_no_live_openalex_search_by_default):
    Paper.objects.create(title="Autonomous driving perception", combined_score=10.0)

    results, count = search_papers_with_live_fallback("autonomous driving")

    assert count == 1
    _no_live_openalex_search_by_default.assert_not_called()


@pytest.mark.django_db
def test_zero_local_results_triggers_live_fetch_and_ingests(
    _no_live_openalex_search_by_default,
):
    _no_live_openalex_search_by_default.return_value = [
        _work("W1", "Autonomous driving in adverse weather", cited_by_count=42),
        _work("W2", "Autonomous driving perception survey", cited_by_count=7),
    ]

    assert Paper.objects.count() == 0
    results, count = search_papers_with_live_fallback("autonomous driving")

    _no_live_openalex_search_by_default.assert_called_once_with(
        "autonomous driving", max_results=5
    )
    assert count == 2
    assert Paper.objects.count() == 2
    titles = {r["title"] for r in results}
    assert titles == {
        "Autonomous driving in adverse weather",
        "Autonomous driving perception survey",
    }


@pytest.mark.django_db
def test_live_fetch_computes_scores_not_left_at_zero(
    _no_live_openalex_search_by_default,
):
    _no_live_openalex_search_by_default.return_value = [
        _work("W1", "Quantum error correction breakthrough", cited_by_count=100),
    ]

    results, _count = search_papers_with_live_fallback("quantum error correction")

    paper = Paper.objects.get(openalex_id="W1")
    # citation_velocity is computed from cited_by_count/years-since-publication
    # (issue #12) -- a nonzero value proves _recompute_scores_for_papers ran,
    # not just ingestion.
    assert paper.citation_velocity > 0
    assert results[0]["citation_velocity"] > 0


@pytest.mark.django_db
def test_openalex_also_empty_returns_no_results(_no_live_openalex_search_by_default):
    _no_live_openalex_search_by_default.return_value = []

    results, count = search_papers_with_live_fallback("zzzz-nonexistent-topic-zzzz")

    assert results == []
    assert count == 0
    assert Paper.objects.count() == 0


@pytest.mark.django_db
def test_openalex_error_degrades_to_empty_not_500(_no_live_openalex_search_by_default):
    _no_live_openalex_search_by_default.side_effect = OpenAlexClientError(
        "network error", status_code=None
    )

    results, count = search_papers_with_live_fallback("some topic")

    assert results == []
    assert count == 0
    assert Paper.objects.count() == 0


@pytest.mark.django_db
def test_on_fallback_callback_receives_work_count(_no_live_openalex_search_by_default):
    _no_live_openalex_search_by_default.return_value = [_work("W1", "Some paper")]
    seen = []

    search_papers_with_live_fallback(
        "some topic", on_fallback=lambda work_count: seen.append(work_count)
    )

    assert seen == [1]


@pytest.mark.django_db
def test_validation_errors_propagate_without_calling_openalex(
    _no_live_openalex_search_by_default,
):
    with pytest.raises(ValueError):
        search_papers_with_live_fallback("   ")

    _no_live_openalex_search_by_default.assert_not_called()


@pytest.mark.django_db
def test_re_run_after_fallback_matches_plain_search_papers(
    _no_live_openalex_search_by_default,
):
    _no_live_openalex_search_by_default.return_value = [
        _work("W1", "Neural network pruning techniques", cited_by_count=5),
    ]

    fallback_results, fallback_count = search_papers_with_live_fallback(
        "neural network pruning"
    )
    plain_results, plain_count = search_papers("neural network pruning")

    assert fallback_results == plain_results
    assert fallback_count == plain_count


@pytest.mark.django_db
def test_ingestion_failure_degrades_to_empty_result_not_raise(
    _no_live_openalex_search_by_default,
):
    """A production incident: any failure during ingest/score must not
    surface as a 500 to a search request -- the fallback is a best-effort
    enhancement on top of an already-valid empty result."""
    _no_live_openalex_search_by_default.return_value = [
        _work("W1", "Some paper", cited_by_count=1),
    ]

    with patch(
        "papers.services.ingestion.ingest_works", side_effect=RuntimeError("boom")
    ):
        results, count = search_papers_with_live_fallback("some topic")

    assert results == []
    assert count == 0


@pytest.mark.django_db
def test_scoring_failure_degrades_to_empty_result_not_raise(
    _no_live_openalex_search_by_default,
):
    _no_live_openalex_search_by_default.return_value = [
        _work("W1", "Some paper", cited_by_count=1),
    ]

    with patch(
        "papers.services._recompute_scores_for_papers",
        side_effect=RuntimeError("boom"),
    ):
        results, count = search_papers_with_live_fallback("some other topic")

    assert results == []
    assert count == 0


@pytest.mark.django_db
def test_highly_collaborative_work_authors_truncated_before_ingest(
    _no_live_openalex_search_by_default,
):
    """Diagnosed against production (2026-09-09): a materials-science
    query returned works with dozens of co-authors, and ingesting all of
    them was the actual cause of a ~30s-plus request that a platform
    timeout then killed. Only the first author is ever read for scoring
    (issue #13), so truncating costs nothing functionally here."""
    many_authors = [
        OpenAlexAuthor(openalex_id=f"A{i}", name=f"Author {i}") for i in range(20)
    ]
    _no_live_openalex_search_by_default.return_value = [
        OpenAlexWork(
            openalex_id="W1",
            title="Highly collaborative paper",
            publication_year=2023,
            doi=None,
            abstract=None,
            venue=None,
            authors=many_authors,
            cited_by_count=1,
            counts_by_year=[],
        )
    ]

    from papers.models import Paper

    search_papers_with_live_fallback("some collaborative topic")

    paper = Paper.objects.get(openalex_id="W1")
    assert paper.authorships.count() <= 5
