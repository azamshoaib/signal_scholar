"""Tests for the `ingest_openalex` management command.

Per GitHub issue #9: `search_works` is patched at its import site in the
command module (`papers.management.commands.ingest_openalex.search_works`),
following the mocking pattern used in #8's own `tests/test_openalex_client.py`
— no live network call.

Fixture set (per issue #9's acceptance criteria):
- one work with a venue and two authors, where the first author has two
  institutions and the second has zero;
- one work with `venue=None`;
- one work with `publication_year=None` and `doi=None`;
- two works that share one common author (same `openalex_id`) and the same
  venue, to exercise the within-run get-or-create path.
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

_SHARED_VENUE = OpenAlexVenue(openalex_id="S1", name="Shared Venue")
_SHARED_AUTHOR = OpenAlexAuthor(openalex_id="A_SHARED", name="Shared Author", institutions=[])


def _sample_works() -> list[OpenAlexWork]:
    return [
        # Work 1: a venue, and two authors — first has two institutions,
        # second has none.
        OpenAlexWork(
            openalex_id="W1",
            title="Work One",
            publication_year=2020,
            doi="10.1/one",
            abstract="Abstract one",
            venue=OpenAlexVenue(openalex_id="S2", name="Solo Venue"),
            authors=[
                OpenAlexAuthor(
                    openalex_id="A1",
                    name="First Author",
                    institutions=[
                        OpenAlexInstitution(openalex_id="I1", name="First Institution"),
                        OpenAlexInstitution(openalex_id="I2", name="Second Institution"),
                    ],
                ),
                OpenAlexAuthor(openalex_id="A2", name="Second Author", institutions=[]),
            ],
        ),
        # Work 2: venue=None.
        OpenAlexWork(
            openalex_id="W2",
            title="Work Two",
            publication_year=2021,
            doi="10.1/two",
            abstract="Abstract two",
            venue=None,
            authors=[],
        ),
        # Work 3: publication_year=None, doi=None.
        OpenAlexWork(
            openalex_id="W3",
            title="Work Three",
            publication_year=None,
            doi=None,
            abstract=None,
            venue=None,
            authors=[],
        ),
        # Work 4 and 5: share one author (A_SHARED) and the same venue
        # (S1), to exercise the within-run get-or-create path.
        OpenAlexWork(
            openalex_id="W4",
            title="Work Four",
            publication_year=2022,
            doi="10.1/four",
            abstract="Abstract four",
            venue=_SHARED_VENUE,
            authors=[_SHARED_AUTHOR],
        ),
        OpenAlexWork(
            openalex_id="W5",
            title="Work Five",
            publication_year=2023,
            doi="10.1/five",
            abstract="Abstract five",
            venue=_SHARED_VENUE,
            authors=[_SHARED_AUTHOR],
        ),
    ]


@pytest.mark.django_db
def test_ingest_openalex_creates_expected_rows_and_prints_counts():
    out = StringIO()
    with patch(
        "papers.management.commands.ingest_openalex.search_works",
        return_value=_sample_works(),
    ) as mock_search_works:
        call_command("ingest_openalex", "machine learning", stdout=out)

    # search_works was called with the topic and default max_results.
    mock_search_works.assert_called_once_with("machine learning", max_results=25)

    # --- Exact row counts -------------------------------------------------
    assert Paper.objects.count() == 5
    # Authors: A1, A2, A_SHARED (shared across W4/W5, not duplicated) = 3.
    assert Author.objects.count() == 3
    # Institutions: only institutions[0] per author is stored — I1 for A1
    # (I2 discarded). No other author has an institution.
    assert Institution.objects.count() == 1
    # Venues: Solo Venue (S2) + Shared Venue (S1, not duplicated) = 2.
    assert Venue.objects.count() == 2
    # Authorships: 2 (work 1) + 0 + 0 + 1 (work 4) + 1 (work 5) = 4.
    assert PaperAuthorship.objects.count() == 4

    # --- Nullable fields don't block Paper creation ------------------------
    work_two = Paper.objects.get(openalex_id="W2")
    assert work_two.venue is None

    work_three = Paper.objects.get(openalex_id="W3")
    assert work_three.publication_year is None
    assert work_three.doi is None

    # --- Position ordering matches list order on the multi-author work ----
    work_one = Paper.objects.get(openalex_id="W1")
    authorships = list(
        PaperAuthorship.objects.filter(paper=work_one).order_by("position")
    )
    assert [a.position for a in authorships] == [1, 2]
    assert authorships[0].author.openalex_id == "A1"
    assert authorships[1].author.openalex_id == "A2"

    # --- Shared author/venue across W4/W5 produced exactly one row each ---
    shared_author = Author.objects.get(openalex_id="A_SHARED")
    assert PaperAuthorship.objects.filter(author=shared_author).count() == 2

    shared_venue = Venue.objects.get(openalex_id="S1")
    assert Paper.objects.filter(venue=shared_venue).count() == 2

    # --- First author's institution is the *first* in their list ----------
    first_author = Author.objects.get(openalex_id="A1")
    assert first_author.institution is not None
    assert first_author.institution.openalex_id == "I1"
    assert first_author.institution.name == "First Institution"
    # The second institution (I2) is discarded entirely.
    assert not Institution.objects.filter(openalex_id="I2").exists()

    second_author = Author.objects.get(openalex_id="A2")
    assert second_author.institution is None

    # --- Printed output contains the four correct counts -------------------
    output = out.getvalue()
    assert "5" in output  # Papers created
    assert "Papers created: 5" in output
    assert "Authors created: 3" in output
    assert "Institutions created: 1" in output
    assert "Venues created: 2" in output


@pytest.mark.django_db
def test_ingest_openalex_passes_topic_and_max_results_through():
    with patch(
        "papers.management.commands.ingest_openalex.search_works",
        return_value=[],
    ) as mock_search_works:
        call_command("ingest_openalex", "quantum computing", "--max-results", "10")

    mock_search_works.assert_called_once_with("quantum computing", max_results=10)


@pytest.mark.django_db
def test_ingest_openalex_second_occurrence_does_not_overwrite_institution():
    """A shared author's institution is set only on first occurrence in the run.

    Reuses the same shared-author fixture (institutions=[]), but here we
    make the *first* occurrence's author carry an institution and confirm a
    second work in the same batch, also referencing that author (with a
    would-be-different institution), does not touch it — first occurrence
    wins.
    """
    author_with_institution = OpenAlexAuthor(
        openalex_id="A_FIRST_WINS",
        name="First Wins Author",
        institutions=[OpenAlexInstitution(openalex_id="I_FIRST", name="First Seen Institution")],
    )
    same_author_different_institution_list = OpenAlexAuthor(
        openalex_id="A_FIRST_WINS",
        name="First Wins Author",
        institutions=[OpenAlexInstitution(openalex_id="I_SECOND", name="Second Seen Institution")],
    )
    works = [
        OpenAlexWork(
            openalex_id="WA",
            title="Work A",
            publication_year=2020,
            doi=None,
            abstract=None,
            venue=None,
            authors=[author_with_institution],
        ),
        OpenAlexWork(
            openalex_id="WB",
            title="Work B",
            publication_year=2020,
            doi=None,
            abstract=None,
            venue=None,
            authors=[same_author_different_institution_list],
        ),
    ]

    with patch(
        "papers.management.commands.ingest_openalex.search_works",
        return_value=works,
    ):
        call_command("ingest_openalex", "topic")

    assert Author.objects.filter(openalex_id="A_FIRST_WINS").count() == 1
    author = Author.objects.get(openalex_id="A_FIRST_WINS")
    assert author.institution.openalex_id == "I_FIRST"
    # The second institution was never even created.
    assert not Institution.objects.filter(openalex_id="I_SECOND").exists()


@pytest.mark.django_db
def test_ingest_openalex_no_authors_or_venue_still_creates_paper():
    works = [
        OpenAlexWork(
            openalex_id="WSOLO",
            title="Solo Work",
            publication_year=None,
            doi=None,
            abstract=None,
            venue=None,
            authors=[],
        ),
    ]

    with patch(
        "papers.management.commands.ingest_openalex.search_works",
        return_value=works,
    ):
        call_command("ingest_openalex", "topic")

    assert Paper.objects.filter(openalex_id="WSOLO").exists()
    assert PaperAuthorship.objects.count() == 0
