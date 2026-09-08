"""Tests for the `fetch_semantic_scholar_embeddings` management command.

Per GitHub issue #21: `semantic_scholar_client.get_papers` is patched at
its import site in the command module
(`papers.management.commands.fetch_semantic_scholar_embeddings.get_papers`),
mirroring #9's `test_ingest_openalex.py` mocking pattern -- no live
network call, and `get_paper` (singular) is asserted to never be called,
since the whole point of #21's batching AC is avoiding an N+1 pattern
against a tightly rate-limited API (#20).
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from papers.models import Paper
from semantic_scholar_client import SemanticScholarClientError, SemanticScholarPaper

_PATCH_TARGET = (
    "papers.management.commands.fetch_semantic_scholar_embeddings.get_papers"
)
_EMBEDDING = [round(0.001 * i, 6) for i in range(768)]
_OTHER_EMBEDDING = [round(0.002 * i, 6) for i in range(768)]


def _run_command() -> str:
    out = StringIO()
    call_command("fetch_semantic_scholar_embeddings", stdout=out)
    return out.getvalue()


def _s2_paper(
    doi: str,
    embedding: list[float] | None = _EMBEDDING,
    *,
    citation_count: int = 100,
    influential_citation_count: int = 26,
) -> SemanticScholarPaper:
    return SemanticScholarPaper(
        semantic_scholar_id=f"s2-{doi}",
        doi=doi,
        embedding=embedding,
        citation_count=citation_count,
        influential_citation_count=influential_citation_count,
    )


# --- Core behavior: matched / unmatched / no-DOI, single small batch -----


@pytest.mark.django_db
@patch(_PATCH_TARGET)
def test_matched_unmatched_and_no_doi_papers_handled_in_one_call(mock_get_papers):
    matched_paper = Paper.objects.create(title="Matched paper", doi="10.1/matched")
    unmatched_paper = Paper.objects.create(
        title="Unmatched paper", doi="10.1/unmatched", influential_citation_ratio=0.42
    )
    no_doi_paper = Paper.objects.create(title="No DOI paper", doi=None)

    # Positionally aligned with the DOIs get_papers is called with below:
    # matched DOI gets a real result, unmatched DOI gets None.
    mock_get_papers.return_value = [
        _s2_paper("10.1/matched", citation_count=100, influential_citation_count=26),
        None,
    ]

    output = _run_command()

    matched_paper.refresh_from_db()
    unmatched_paper.refresh_from_db()
    no_doi_paper.refresh_from_db()

    assert list(matched_paper.embedding) == _EMBEDDING
    assert matched_paper.influential_citation_ratio == pytest.approx(26 / 100)
    assert unmatched_paper.embedding is None
    # Unchanged from its pre-run value -- identical "leave untouched"
    # semantics to embedding on a "no Semantic Scholar match" result.
    assert unmatched_paper.influential_citation_ratio == pytest.approx(0.42)
    assert no_doi_paper.embedding is None
    assert no_doi_paper.influential_citation_ratio == 0.0

    # get_papers called exactly once, with the full batch of DOIs
    # (doi=None papers excluded) -- not once per paper.
    mock_get_papers.assert_called_once()
    called_dois = mock_get_papers.call_args.args[0]
    assert called_dois == ["10.1/matched", "10.1/unmatched"]

    assert "Papers processed: 2" in output
    assert "Papers matched: 1" in output
    assert "Papers skipped (no DOI): 1" in output
    assert "No Semantic Scholar match: 1" in output


@pytest.mark.django_db
def test_get_paper_singular_is_never_called():
    Paper.objects.create(title="Some paper", doi="10.1/x")

    with (
        patch(_PATCH_TARGET, return_value=[_s2_paper("10.1/x")]) as mock_get_papers,
        patch("semantic_scholar_client.get_paper") as mock_get_paper,
    ):
        _run_command()

    mock_get_papers.assert_called_once()
    mock_get_paper.assert_not_called()


@pytest.mark.django_db
@patch(_PATCH_TARGET)
def test_no_doi_papers_never_trigger_a_call_when_that_is_the_only_paper(mock_get_papers):
    Paper.objects.create(title="No DOI paper", doi=None)

    output = _run_command()

    mock_get_papers.assert_not_called()
    assert "Papers processed: 0" in output
    assert "Papers skipped (no DOI): 1" in output


@pytest.mark.django_db
@patch(_PATCH_TARGET)
def test_empty_database_prints_zero_counts_no_errors(mock_get_papers):
    output = _run_command()

    mock_get_papers.assert_not_called()
    assert "Papers processed: 0" in output
    assert "Papers matched: 0" in output
    assert "Papers skipped (no DOI): 0" in output
    assert "No Semantic Scholar match: 0" in output


@pytest.mark.django_db
@patch(_PATCH_TARGET)
def test_zero_citation_count_falls_back_to_zero_ratio_no_zero_division(mock_get_papers):
    # citation_count=0 with a *nonzero* influential_citation_count proves
    # the zero-division guard actually fires, rather than both being
    # coincidentally zero.
    paper = Paper.objects.create(title="Uncited paper", doi="10.1/uncited")
    mock_get_papers.return_value = [
        _s2_paper("10.1/uncited", citation_count=0, influential_citation_count=3)
    ]

    _run_command()

    paper.refresh_from_db()
    assert paper.influential_citation_ratio == 0.0


# --- Re-running overwrites unconditionally --------------------------------


@pytest.mark.django_db
@patch(_PATCH_TARGET)
def test_rerun_overwrites_embedding_unconditionally(mock_get_papers):
    paper = Paper.objects.create(title="Paper", doi="10.1/x", embedding=_EMBEDDING)

    mock_get_papers.return_value = [_s2_paper("10.1/x", embedding=_OTHER_EMBEDDING)]
    _run_command()

    paper.refresh_from_db()
    assert list(paper.embedding) == _OTHER_EMBEDDING


# --- Chunking boundary: >500 papers -> multiple calls, each <=500 DOIs ---


@pytest.mark.django_db
def test_more_than_500_papers_are_chunked_into_multiple_calls():
    total_papers = 650
    Paper.objects.bulk_create(
        [
            Paper(title=f"Paper {i}", doi=f"10.1/paper-{i}")
            for i in range(total_papers)
        ]
    )

    def _side_effect(dois):
        assert len(dois) <= 500
        return [_s2_paper(doi) for doi in dois]

    with patch(_PATCH_TARGET, side_effect=_side_effect) as mock_get_papers:
        output = _run_command()

    assert mock_get_papers.call_count == 2
    call_sizes = sorted(len(call.args[0]) for call in mock_get_papers.call_args_list)
    assert call_sizes == [150, 500]
    assert "Papers processed: 650" in output
    assert "Papers matched: 650" in output
    assert Paper.objects.filter(embedding__isnull=False).count() == 650


# --- CommandError + accurate partial progress on a mid-run failure -------


@pytest.mark.django_db
def test_failure_on_later_chunk_raises_command_error_with_partial_progress():
    total_papers = 650
    Paper.objects.bulk_create(
        [
            Paper(title=f"Paper {i}", doi=f"10.1/paper-{i}")
            for i in range(total_papers)
        ]
    )

    call_count = 0

    def _side_effect(dois):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [_s2_paper(doi) for doi in dois]
        raise SemanticScholarClientError("boom", status_code=429)

    with patch(_PATCH_TARGET, side_effect=_side_effect):
        with pytest.raises(CommandError) as exc_info:
            _run_command()

    message = str(exc_info.value)
    assert "1" in message  # 1 chunk / however-many papers succeeded
    assert "500" in message or "chunk" in message.lower()

    # First chunk's progress (500 papers) must have been saved before the
    # second chunk's failure -- not lost, not rolled back.
    assert Paper.objects.filter(embedding__isnull=False).count() == 500
    assert Paper.objects.filter(embedding__isnull=True).count() == 150
