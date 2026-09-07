"""Tests for re-running `ingest_openalex` against an overlapping result set.

Per GitHub issue #10: `Paper` must be matched/updated by `openalex_id`
across separate invocations of the command, instead of always creating a
fresh row (which crashed with an `IntegrityError` on `Paper.doi`'s unique
constraint whenever OpenAlex returned a work already ingested by a
previous run).

Kept separate from #9's `tests/test_ingest_openalex.py`, which only
exercises within-batch/single-run dedup and must keep passing unmodified.
As in #9, `search_works` is patched at its import site in the command
module (`papers.management.commands.ingest_openalex.search_works`) — no
live network call.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from openalex_client import (
    OpenAlexAuthor,
    OpenAlexInstitution,
    OpenAlexVenue,
    OpenAlexWork,
)
from papers.models import Author, Institution, Paper, PaperAuthorship, Venue


def _run(works, out: StringIO | None = None) -> str:
    """Call the command with `works` mocked as the `search_works` result."""
    stdout = out if out is not None else StringIO()
    with patch(
        "papers.management.commands.ingest_openalex.search_works",
        return_value=works,
    ):
        call_command("ingest_openalex", "topic", stdout=stdout)
    return stdout.getvalue()


def _base_work(**overrides) -> OpenAlexWork:
    """A work with a venue, one author, and one institution, for reuse."""
    defaults = dict(
        openalex_id="W1",
        title="Original Title",
        publication_year=2020,
        doi="10.1/original",
        abstract="Original abstract",
        venue=OpenAlexVenue(openalex_id="S1", name="Original Venue"),
        authors=[
            OpenAlexAuthor(
                openalex_id="A1",
                name="Original Author",
                institutions=[
                    OpenAlexInstitution(openalex_id="I1", name="Original Institution")
                ],
            )
        ],
    )
    defaults.update(overrides)
    return OpenAlexWork(**defaults)


@pytest.mark.django_db
def test_identical_rerun_keeps_row_counts_constant():
    works = [_base_work()]

    _run(works)
    _run(works)

    assert Paper.objects.count() == 1
    assert Author.objects.count() == 1
    assert Institution.objects.count() == 1
    assert Venue.objects.count() == 1
    assert PaperAuthorship.objects.count() == 1

    paper = Paper.objects.get(openalex_id="W1")
    assert paper.title == "Original Title"
    assert paper.doi == "10.1/original"


@pytest.mark.django_db
def test_second_run_reports_paper_updated_not_created():
    works = [_base_work()]

    _run(works)
    output = _run(works)

    assert "Papers created: 0" in output
    assert "Papers updated: 1" in output


@pytest.mark.django_db
def test_changed_title_abstract_and_names_update_in_place():
    _run([_base_work()])
    first_paper_pk = Paper.objects.get(openalex_id="W1").pk
    first_author_pk = Author.objects.get(openalex_id="A1").pk
    first_institution = Author.objects.get(openalex_id="A1").institution
    assert first_institution is not None
    assert first_institution.openalex_id == "I1"

    changed_work = _base_work(
        title="Updated Title",
        publication_year=2021,
        abstract="Updated abstract",
        venue=OpenAlexVenue(openalex_id="S1", name="Updated Venue"),
        authors=[
            OpenAlexAuthor(
                openalex_id="A1",
                name="Updated Author",
                # Different institution data — must NOT be applied, since
                # Author.institution is first-occurrence-wins (issue #9)
                # and reconciling it across a match is deferred to #30.
                institutions=[
                    OpenAlexInstitution(openalex_id="I2", name="Updated Institution")
                ],
            )
        ],
    )
    _run([changed_work])

    # Same underlying rows (same PKs), not new ones.
    assert Paper.objects.count() == 1
    assert Author.objects.count() == 1

    paper = Paper.objects.get(pk=first_paper_pk)
    assert paper.title == "Updated Title"
    assert paper.publication_year == 2021
    assert paper.abstract == "Updated abstract"
    assert paper.venue is not None
    assert paper.venue.name == "Updated Venue"

    venue = Venue.objects.get(openalex_id="S1")
    assert venue.name == "Updated Venue"

    author = Author.objects.get(pk=first_author_pk)
    assert author.name == "Updated Author"
    # Author.institution is unchanged from the first run, even though the
    # fixture's institution data changed on the second run.
    assert author.institution is not None
    assert author.institution.openalex_id == "I1"
    assert author.institution.name == "Original Institution"
    # The would-be-new institution from the second run was never created.
    assert not Institution.objects.filter(openalex_id="I2").exists()


@pytest.mark.django_db
def test_doi_conflict_preserves_stored_value_and_warns():
    _run([_base_work()])

    conflicting_work = _base_work(doi="10.1/different")
    output = _run([conflicting_work])

    paper = Paper.objects.get(openalex_id="W1")
    assert paper.doi == "10.1/original"
    assert Paper.objects.count() == 1

    assert "W1" in output
    assert "10.1/original" in output
    assert "10.1/different" in output


@pytest.mark.django_db
def test_doi_conflict_second_run_missing_doi_keeps_stored():
    _run([_base_work()])

    work_without_doi = _base_work(doi=None)
    _run([work_without_doi])

    paper = Paper.objects.get(openalex_id="W1")
    assert paper.doi == "10.1/original"


@pytest.mark.django_db
def test_doi_filled_in_when_previously_missing():
    _run([_base_work(doi=None)])
    paper = Paper.objects.get(openalex_id="W1")
    assert paper.doi is None

    _run([_base_work(doi="10.1/filled-in")])
    paper.refresh_from_db()
    assert paper.doi == "10.1/filled-in"


@pytest.mark.django_db
def test_paper_authorship_reconciles_on_changed_author_list():
    author_a = OpenAlexAuthor(openalex_id="AA", name="Author A", institutions=[])
    author_b = OpenAlexAuthor(openalex_id="AB", name="Author B", institutions=[])
    author_c = OpenAlexAuthor(openalex_id="AC", name="Author C", institutions=[])

    first_work = _base_work(authors=[author_a, author_b])
    _run([first_work])

    paper = Paper.objects.get(openalex_id="W1")
    first_run_authorships = list(
        PaperAuthorship.objects.filter(paper=paper).order_by("position")
    )
    assert [a.author.openalex_id for a in first_run_authorships] == ["AA", "AB"]

    # Second run: drop AA, keep AB but move it, add AC — reordered.
    second_work = _base_work(authors=[author_c, author_b])
    _run([second_work])

    authorships = list(
        PaperAuthorship.objects.filter(paper=paper).order_by("position")
    )
    assert [(a.author.openalex_id, a.position) for a in authorships] == [
        ("AC", 1),
        ("AB", 2),
    ]
    # No stale leftover row for the dropped author AA.
    assert not PaperAuthorship.objects.filter(author__openalex_id="AA").exists()
    # Exactly two authorship rows remain for this paper.
    assert PaperAuthorship.objects.filter(paper=paper).count() == 2


@pytest.mark.django_db
def test_openalex_id_none_never_dedupes_across_runs():
    def _work_without_openalex_id(doi: str) -> OpenAlexWork:
        return OpenAlexWork(
            openalex_id=None,
            title="No External ID Work",
            publication_year=2020,
            doi=doi,
            abstract="Abstract",
            venue=None,
            authors=[],
        )

    _run([_work_without_openalex_id("10.1/no-id-one")])
    _run([_work_without_openalex_id("10.1/no-id-two")])

    assert Paper.objects.filter(openalex_id__isnull=True).count() == 2
