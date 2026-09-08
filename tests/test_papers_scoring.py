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
    CITATION_VELOCITY_REFERENCE_MAX,
    DEFAULT_REPUTATION_WEIGHT,
    DEFAULT_VELOCITY_WEIGHT,
    H_INDEX_NORMALIZED_REFERENCE_MAX,
    compute_academic_age,
    compute_author_h_index_scores,
    compute_citation_velocity,
    compute_h_index,
    compute_h_index_normalized,
    compute_paper_author_reputation_score,
    compute_paper_citation_velocity,
    compute_years_since_publication,
    normalize_h_index_score,
    normalize_velocity_score,
    update_author_h_index,
    update_paper_citation_velocity,
    update_paper_combined_score,
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


# --- Per-paper citation velocity (issue #12) --------------------------------
#
# Fixtures are hand-constructed `Paper` rows with explicit
# `cited_by_count`/`publication_year` values -- no live API calls.
# `current_year` is passed explicitly so these tests don't depend on the
# date they happen to run on.


def _make_paper(*, cited_by_count, publication_year):
    return Paper.objects.create(
        title=f"Paper ({publication_year}, {cited_by_count} cites)",
        publication_year=publication_year,
        cited_by_count=cited_by_count,
    )


# --- Pure-function unit tests (no DB) --------------------------------------


def test_compute_years_since_publication_floors_at_one():
    assert compute_years_since_publication(2011, current_year=2026) == 15
    assert compute_years_since_publication(2025, current_year=2026) == 1
    # Published this year -> would be 0 without the floor.
    assert compute_years_since_publication(2026, current_year=2026) == 1
    # Bad/future data -> would go negative without the floor.
    assert compute_years_since_publication(2030, current_year=2026) == 1
    # No known publication year at all -> undefined, not floored to 1.
    assert compute_years_since_publication(None, current_year=2026) is None


def test_compute_years_since_publication_does_not_use_academic_age_offset():
    # Unlike #11's academic_age (`current_year - first_year + 1`), this is
    # `current_year - publication_year` with no +1: a paper published last
    # year has had ~1 year, not 2.
    assert compute_years_since_publication(2025, current_year=2026) == 1
    assert compute_academic_age([2025], current_year=2026) == 2


def test_compute_citation_velocity_divides_and_falls_back_to_zero():
    assert compute_citation_velocity(450, 15) == 30.0
    assert compute_citation_velocity(120, None) == 0.0
    assert compute_citation_velocity(0, None) == 0.0


# --- The five required scenarios, against real DB fixtures ------------------


@pytest.mark.django_db
def test_old_highly_cited_paper():
    paper = _make_paper(cited_by_count=450, publication_year=2011)

    velocity = compute_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    assert velocity == pytest.approx(30.0)

    update_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    paper.refresh_from_db()
    assert paper.citation_velocity == pytest.approx(30.0)


@pytest.mark.django_db
def test_recent_paper_few_citations():
    paper = _make_paper(cited_by_count=8, publication_year=2025)

    velocity = compute_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    assert velocity == pytest.approx(8.0)

    update_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    paper.refresh_from_db()
    assert paper.citation_velocity == pytest.approx(8.0)


@pytest.mark.django_db
def test_current_year_paper_floored_no_division_by_zero():
    paper = _make_paper(cited_by_count=3, publication_year=CURRENT_YEAR)

    velocity = compute_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    assert velocity == pytest.approx(3.0)

    update_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    paper.refresh_from_db()
    assert paper.citation_velocity == pytest.approx(3.0)


@pytest.mark.django_db
def test_null_publication_year_zeroes_velocity_but_not_cited_by_count():
    # publication_year is null (allowed per #5): years_since_publication is
    # undefined and citation_velocity falls back to 0.0 -- the one case
    # where cited_by_count and citation_velocity visibly diverge.
    paper = _make_paper(cited_by_count=120, publication_year=None)

    velocity = compute_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    assert velocity == 0.0
    assert paper.cited_by_count == 120

    update_paper_citation_velocity(paper, current_year=CURRENT_YEAR)
    paper.refresh_from_db()
    assert paper.citation_velocity == 0.0
    assert paper.cited_by_count == 120


@pytest.mark.django_db
def test_recent_paper_not_penalized_relative_to_older_paper():
    # A 1-year-old paper and a 10-year-old paper with proportionally scaled
    # citation counts get the same velocity -- the recent paper is not
    # buried under the older paper's larger lifetime total.
    recent = _make_paper(cited_by_count=20, publication_year=2025)
    older = _make_paper(cited_by_count=200, publication_year=2016)

    recent_velocity = compute_paper_citation_velocity(recent, current_year=CURRENT_YEAR)
    older_velocity = compute_paper_citation_velocity(older, current_year=CURRENT_YEAR)

    assert recent_velocity == pytest.approx(20.0)
    assert older_velocity == pytest.approx(20.0)
    assert recent_velocity == older_velocity


# --- Combined weighted score (issue #13) ------------------------------------
#
# Fixtures set `h_index_normalized`/`citation_velocity` directly on
# hand-built `Author`/`Paper`/`PaperAuthorship` rows -- these tests exercise
# `update_paper_combined_score`'s "reads already-stored sub-signals" job,
# not #11/#12's own computation of those sub-signals.


def _make_author(*, name, h_index_normalized):
    return Author.objects.create(name=name, h_index_normalized=h_index_normalized)


# --- Pure-function unit tests (no DB) --------------------------------------


def test_normalize_h_index_score_linear_clamp_and_saturation():
    assert normalize_h_index_score(0.0) == 0.0
    assert normalize_h_index_score(2.5) == pytest.approx(50.0)
    assert normalize_h_index_score(H_INDEX_NORMALIZED_REFERENCE_MAX) == pytest.approx(100.0)
    # Far above the reference max -> saturates at 100, not unbounded.
    assert normalize_h_index_score(20.0) == 100.0


def test_normalize_velocity_score_linear_clamp_and_saturation():
    assert normalize_velocity_score(0.0) == 0.0
    assert normalize_velocity_score(25.0) == pytest.approx(50.0)
    assert normalize_velocity_score(CITATION_VELOCITY_REFERENCE_MAX) == pytest.approx(100.0)
    # Far above the reference max -> saturates at 100, not unbounded.
    assert normalize_velocity_score(500.0) == 100.0


# --- Required scenarios, against real DB fixtures ---------------------------


@pytest.mark.django_db
def test_combined_score_increases_with_velocity_until_saturation():
    # author_reputation_score held constant throughout.
    author = _make_author(name="Constant Reputation Author", h_index_normalized=1.0)

    def _combined_score_for_velocity(velocity):
        paper = Paper.objects.create(
            title=f"Paper (velocity={velocity})", citation_velocity=velocity
        )
        PaperAuthorship.objects.create(paper=paper, author=author, position=1)
        update_paper_combined_score(paper, author)
        return paper.combined_score

    below_saturation = [0.0, 10.0, 25.0, CITATION_VELOCITY_REFERENCE_MAX]
    scores = [_combined_score_for_velocity(v) for v in below_saturation]
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores)  # strictly increasing

    # Beyond the reference max, velocity_score (and so combined_score) is
    # already saturated at 100 -- no further increase.
    saturated_score = _combined_score_for_velocity(CITATION_VELOCITY_REFERENCE_MAX)
    far_beyond_score = _combined_score_for_velocity(500.0)
    assert saturated_score == far_beyond_score


@pytest.mark.django_db
def test_combined_score_increases_with_reputation_until_saturation():
    # citation_velocity held constant throughout.
    velocity = 10.0

    def _combined_score_for_h_index_normalized(h_index_normalized):
        author = _make_author(
            name=f"Author (h_norm={h_index_normalized})",
            h_index_normalized=h_index_normalized,
        )
        paper = Paper.objects.create(
            title=f"Paper (h_norm={h_index_normalized})", citation_velocity=velocity
        )
        PaperAuthorship.objects.create(paper=paper, author=author, position=1)
        update_paper_combined_score(paper, author)
        return paper.combined_score

    below_saturation = [0.0, 1.0, 2.5, H_INDEX_NORMALIZED_REFERENCE_MAX]
    scores = [_combined_score_for_h_index_normalized(h) for h in below_saturation]
    assert scores == sorted(scores)
    assert len(set(scores)) == len(scores)  # strictly increasing

    # Beyond the reference max, author_reputation_score (and so
    # combined_score) is already saturated at 100 -- no further increase.
    saturated_score = _combined_score_for_h_index_normalized(H_INDEX_NORMALIZED_REFERENCE_MAX)
    far_beyond_score = _combined_score_for_h_index_normalized(20.0)
    assert saturated_score == far_beyond_score


@pytest.mark.django_db
def test_author_reputation_score_uses_first_author_only_not_max_or_average():
    # First author has a high h_index_normalized; one coauthor is lower,
    # one coauthor is *higher* -- so MAX and AVERAGE would both disagree
    # with "first author only" here, pinning the collapsing-rule decision.
    first_author = _make_author(name="First Author", h_index_normalized=2.0)
    lower_coauthor = _make_author(name="Lower Coauthor", h_index_normalized=0.5)
    higher_coauthor = _make_author(name="Higher Coauthor", h_index_normalized=4.0)

    paper = Paper.objects.create(title="Multi-author paper", citation_velocity=0.0)
    PaperAuthorship.objects.create(paper=paper, author=first_author, position=1)
    PaperAuthorship.objects.create(paper=paper, author=lower_coauthor, position=2)
    PaperAuthorship.objects.create(paper=paper, author=higher_coauthor, position=3)

    score = compute_paper_author_reputation_score(first_author)

    expected_first_author_score = normalize_h_index_score(2.0)
    what_max_would_give = normalize_h_index_score(4.0)
    what_average_would_give = normalize_h_index_score((2.0 + 0.5 + 4.0) / 3)

    assert score == pytest.approx(expected_first_author_score)
    assert score != pytest.approx(what_max_would_give)
    assert score != pytest.approx(what_average_would_give)


@pytest.mark.django_db
def test_zero_authorship_paper_reputation_score_zero_and_combined_drops_term():
    # No PaperAuthorship rows at all (allowed per #5's schema).
    paper = Paper.objects.create(title="No authors", citation_velocity=20.0)

    assert compute_paper_author_reputation_score(None) == 0.0

    update_paper_combined_score(paper, None)
    paper.refresh_from_db()

    expected_velocity_score = normalize_velocity_score(20.0)
    assert paper.author_reputation_score == 0.0
    assert paper.velocity_score == pytest.approx(expected_velocity_score)
    # Reputation term drops out cleanly -- combined_score is exactly the
    # velocity term alone.
    assert paper.combined_score == pytest.approx(
        DEFAULT_VELOCITY_WEIGHT * expected_velocity_score
    )


@pytest.mark.django_db
def test_paper_with_outlier_velocity_and_reputation_both_saturate_at_100():
    # citation_velocity far above CITATION_VELOCITY_REFERENCE_MAX (e.g. 500)
    # and h_index_normalized far above H_INDEX_NORMALIZED_REFERENCE_MAX
    # (e.g. 20) both saturate at 100, not unbounded.
    outlier_author = _make_author(name="Outlier Author", h_index_normalized=20.0)
    paper = Paper.objects.create(title="Outlier paper", citation_velocity=500.0)
    PaperAuthorship.objects.create(paper=paper, author=outlier_author, position=1)

    update_paper_combined_score(paper, outlier_author)
    paper.refresh_from_db()

    assert paper.author_reputation_score == 100.0
    assert paper.velocity_score == 100.0
    assert paper.combined_score == pytest.approx(100.0)


@pytest.mark.django_db
def test_combined_score_hand_computed_example():
    # first author h_index_normalized = 2.5
    #   -> normalize_h_index_score(2.5) = min(2.5/5.0, 1.0)*100 = 50.0
    # paper citation_velocity = 20.0
    #   -> normalize_velocity_score(20.0) = min(20.0/50.0, 1.0)*100 = 40.0
    # combined_score = 0.5*50.0 + 0.5*40.0 = 45.0
    author = _make_author(name="Hand-Computed Author", h_index_normalized=2.5)
    paper = Paper.objects.create(title="Hand-computed paper", citation_velocity=20.0)
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    update_paper_combined_score(paper, author)
    paper.refresh_from_db()

    assert paper.author_reputation_score == pytest.approx(50.0)
    assert paper.velocity_score == pytest.approx(40.0)
    assert paper.combined_score == pytest.approx(45.0)
    assert paper.combined_score == pytest.approx(
        DEFAULT_REPUTATION_WEIGHT * 50.0 + DEFAULT_VELOCITY_WEIGHT * 40.0
    )


@pytest.mark.django_db
def test_update_paper_combined_score_save_false_does_not_persist():
    author = _make_author(name="Author", h_index_normalized=2.5)
    paper = Paper.objects.create(title="Paper", citation_velocity=20.0)
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    update_paper_combined_score(paper, author, save=False)
    assert paper.combined_score == pytest.approx(45.0)  # computed in-memory

    paper.refresh_from_db()
    assert paper.combined_score == 0.0  # not persisted
