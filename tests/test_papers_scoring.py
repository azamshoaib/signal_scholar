"""Tests for the academic-age-normalized h-index (issue #11).

Fixtures are hand-constructed `Author`/`Paper`/`PaperAuthorship` rows with
explicit `cited_by_count`/`publication_year` values — no live API calls.
`current_year` is passed explicitly to `update_author_h_index` /
`compute_author_h_index_scores` so these tests don't depend on the date
they happen to run on.
"""

import pytest

from papers.models import Author, Paper, PaperAuthorship
from papers.scoring import (
    compute_academic_age,
    compute_author_h_index_scores,
    compute_h_index,
    compute_h_index_normalized,
    update_author_h_index,
)

CURRENT_YEAR = 2026


def _add_paper(author, *, cited_by_count, publication_year, position=1):
    paper = Paper.objects.create(
        title=f"Paper by {author.name} ({publication_year}, {cited_by_count} cites)",
        publication_year=publication_year,
        cited_by_count=cited_by_count,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=position)
    return paper


# --- Pure-function unit tests (no DB) --------------------------------------


def test_compute_h_index_standard_examples():
    # 4 papers with >=4 citations each (10, 8, 5, 4), 5th paper only has 3
    # citations, so h caps at 4, not 5.
    assert compute_h_index([10, 8, 5, 4, 3]) == 4
    # Sorted desc: 20,15,10,9,8,8,7,7,3 -> positions 1-7 all qualify
    # (7th value 7 >= 7), position 8's value 7 < 8 -> h = 7.
    assert compute_h_index([20, 15, 10, 9, 8, 8, 7, 7, 3]) == 7
    assert compute_h_index([]) == 0
    assert compute_h_index([0, 0, 0]) == 0


def test_compute_academic_age_floors_at_one():
    assert compute_academic_age([2020, 2015, None], current_year=2026) == 12
    # First publication this year -> age would be 1 already.
    assert compute_academic_age([2026], current_year=2026) == 1
    # Bad/future data -> would go negative/zero without the floor.
    assert compute_academic_age([2030], current_year=2026) == 1
    # No known publication year at all -> undefined, not floored to 1.
    assert compute_academic_age([None, None], current_year=2026) is None
    assert compute_academic_age([], current_year=2026) is None


def test_compute_h_index_normalized_divides_and_falls_back_to_zero():
    assert compute_h_index_normalized(8, 4) == 2.0
    assert compute_h_index_normalized(5, None) == 0.0
    assert compute_h_index_normalized(0, None) == 0.0


# --- The five required scenarios, against real DB fixtures ------------------


@pytest.mark.django_db
def test_senior_author_high_h_index_lower_normalized_value():
    # Many papers, moderate-to-high citations, a long career.
    senior = Author.objects.create(name="Senior Author")
    citation_counts = [50, 40, 30, 25, 20, 15, 10, 5]
    for i, count in enumerate(citation_counts):
        _add_paper(senior, cited_by_count=count, publication_year=2006 + i)

    h_index, h_index_normalized = compute_author_h_index_scores(
        senior, current_year=CURRENT_YEAR
    )

    # Sorted desc: 50,40,30,25,20,15,10,5 -> position 8 has count 5 < 8,
    # position 7 has count 10 >= 7 -> h = 7.
    assert h_index == 7
    academic_age = compute_academic_age(
        [p.publication_year for p in senior.papers.all()], current_year=CURRENT_YEAR
    )
    assert academic_age == CURRENT_YEAR - 2006 + 1  # 21
    assert h_index_normalized == pytest.approx(7 / 21)

    update_author_h_index(senior, current_year=CURRENT_YEAR)
    senior.refresh_from_db()
    assert senior.h_index == 7
    assert senior.h_index_normalized == pytest.approx(7 / 21)


@pytest.mark.django_db
def test_early_career_author_higher_normalized_value_than_senior():
    # Few papers, high citations, a short career.
    early_career = Author.objects.create(name="Early-Career Author")
    for count in (12, 10, 9):
        _add_paper(early_career, cited_by_count=count, publication_year=2024)

    h_index, h_index_normalized = compute_author_h_index_scores(
        early_career, current_year=CURRENT_YEAR
    )

    # Sorted desc: 12,10,9 -> all three positions qualify (>=1,>=2,>=3) -> h=3.
    assert h_index == 3
    academic_age = CURRENT_YEAR - 2024 + 1  # 3
    assert h_index_normalized == pytest.approx(3 / 3)  # 1.0

    # Build the senior author from the previous scenario for comparison.
    senior = Author.objects.create(name="Senior Author (comparison)")
    for i, count in enumerate([50, 40, 30, 25, 20, 15, 10, 5]):
        _add_paper(senior, cited_by_count=count, publication_year=2006 + i)
    senior_h_index, senior_h_index_normalized = compute_author_h_index_scores(
        senior, current_year=CURRENT_YEAR
    )

    # Raw h-index: early-career author is (correctly) lower.
    assert h_index < senior_h_index
    # Normalized value: early-career author is higher (or at least
    # comparable) despite the much lower raw h-index -- this is the
    # actual point of the signal per the issue's Goal.
    assert h_index_normalized >= senior_h_index_normalized


@pytest.mark.django_db
def test_zero_papers_author():
    author = Author.objects.create(name="No Papers Author")

    h_index, h_index_normalized = compute_author_h_index_scores(
        author, current_year=CURRENT_YEAR
    )

    assert h_index == 0
    assert h_index_normalized == 0.0

    update_author_h_index(author, current_year=CURRENT_YEAR)
    author.refresh_from_db()
    assert author.h_index == 0
    assert author.h_index_normalized == 0.0


@pytest.mark.django_db
def test_all_null_publication_year_zeroes_normalized_but_not_raw_h_index():
    # Every paper has a null publication_year: h_index is still computed
    # normally from cited_by_count, but academic age is undefined, so
    # h_index_normalized falls back to 0.0. This is the asymmetric case
    # called out explicitly in the issue and needs its own test.
    author = Author.objects.create(name="Unknown-Year Author")
    for count in (9, 7, 6, 2):
        _add_paper(author, cited_by_count=count, publication_year=None)

    h_index, h_index_normalized = compute_author_h_index_scores(
        author, current_year=CURRENT_YEAR
    )

    # Sorted desc: 9,7,6,2 -> positions 1-3 qualify (>=1,>=2,>=3), position
    # 4 has count 2 < 4 -> h = 3.
    assert h_index == 3
    assert h_index != 0
    assert h_index_normalized == 0.0

    update_author_h_index(author, current_year=CURRENT_YEAR)
    author.refresh_from_db()
    assert author.h_index == 3
    assert author.h_index_normalized == 0.0


@pytest.mark.django_db
def test_first_year_author_academic_age_floored_to_one_no_division_by_zero():
    # first_publication_year == current_year -> naive academic age would be
    # 1 anyway, but this exercises the floor path explicitly and confirms
    # no ZeroDivisionError / crash.
    author = Author.objects.create(name="First-Year Author")
    _add_paper(author, cited_by_count=4, publication_year=CURRENT_YEAR)

    h_index, h_index_normalized = compute_author_h_index_scores(
        author, current_year=CURRENT_YEAR
    )

    assert h_index == 1
    assert h_index_normalized == pytest.approx(1 / 1)  # 1.0, no ZeroDivisionError

    update_author_h_index(author, current_year=CURRENT_YEAR)
    author.refresh_from_db()
    assert author.h_index == 1
    assert author.h_index_normalized == pytest.approx(1.0)
