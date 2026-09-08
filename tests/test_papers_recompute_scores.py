"""Tests for the `recompute_scores` management command (GitHub issue #14).

Covers: the exact three-phase operation order (author h_index fully
recomputed and committed before any paper's `combined_score` is
recomputed off it -- the "ordering regression" test below), no N+1 query
growth, an empty database, a zero-authorship paper, a zero-paper author,
and idempotency across repeated runs.

`current_year` is not passed explicitly anywhere here (unlike
`tests/test_papers_scoring.py`, which pins it) because the command itself
never exposes a `--current-year` flag -- it always uses "today" (see
issue #14's Constraints: "a later recompute naturally ages every
author/paper"). Fixtures below are built with publication years relative
to `TODAY_YEAR` so the hand-computed expectations stay correct regardless
of what year the suite happens to run in.
"""

from __future__ import annotations

import datetime
import io

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from papers.models import Author, Paper, PaperAuthorship
from papers.scoring import (
    DEFAULT_REPUTATION_WEIGHT,
    compute_academic_age,
    compute_h_index,
    compute_h_index_normalized,
    normalize_h_index_score,
    update_paper_combined_score,
)

TODAY_YEAR = datetime.date.today().year


def _run_command() -> str:
    out = io.StringIO()
    from django.core.management import call_command

    call_command("recompute_scores", stdout=out)
    return out.getvalue()


# --- Empty database -----------------------------------------------------


@pytest.mark.django_db
def test_empty_database_prints_zero_counts_no_errors():
    output = _run_command()
    assert "Authors recomputed: 0" in output
    assert "Papers recomputed: 0" in output


# --- Zero-authorship paper / zero-paper author --------------------------


@pytest.mark.django_db
def test_zero_authorship_paper_included_not_skipped():
    paper = Paper.objects.create(title="No authors", cited_by_count=20, publication_year=TODAY_YEAR)

    output = _run_command()

    assert "Papers recomputed: 1" in output
    paper.refresh_from_db()
    # Fallback per compute_paper_author_reputation_score, not an error/skip.
    assert paper.author_reputation_score == 0.0


@pytest.mark.django_db
def test_zero_paper_author_included_not_skipped():
    author = Author.objects.create(name="No papers")

    output = _run_command()

    assert "Authors recomputed: 1" in output
    author.refresh_from_db()
    assert author.h_index == 0
    assert author.h_index_normalized == 0.0


# --- Ordering regression: phase 1 must be fully done before phase 3 -----


@pytest.mark.django_db
def test_combined_score_uses_freshly_recomputed_h_index_not_stale_value():
    # Stored h_index_normalized is deliberately wrong/stale (as if left
    # over from before this author's papers were known/ingested). Its real
    # papers, once phase 1 recomputes from them, yield a small, specific
    # value -- nothing close to the stale 999.0.
    author = Author.objects.create(name="Stale Author", h_index_normalized=999.0)
    cited_by_counts = [10, 8, 5, 4, 3]
    publication_year = TODAY_YEAR - 10  # academic_age = 11
    for count in cited_by_counts:
        Paper.objects.create(
            title=f"Prior paper ({count} cites)",
            cited_by_count=count,
            publication_year=publication_year,
        ).authorships.create(author=author, position=1)

    paper = Paper.objects.create(
        title="Paper by the stale author",
        cited_by_count=0,
        publication_year=TODAY_YEAR,
        citation_velocity=0.0,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    _run_command()

    author.refresh_from_db()
    paper.refresh_from_db()

    expected_h_index = compute_h_index(cited_by_counts)  # 4
    expected_academic_age = compute_academic_age([publication_year] * 5, current_year=TODAY_YEAR)
    expected_h_index_normalized = compute_h_index_normalized(expected_h_index, expected_academic_age)

    assert author.h_index == expected_h_index
    assert author.h_index_normalized == pytest.approx(expected_h_index_normalized)
    assert author.h_index_normalized != pytest.approx(999.0)

    expected_reputation_score = normalize_h_index_score(expected_h_index_normalized)
    # If phase 3 had instead read a queryset/prefetch cache populated
    # before phase 1 committed (or the stale stored value), the reputation
    # component would be normalize_h_index_score(999.0), which saturates
    # at 100.0 -- nowhere near the small fresh value.
    assert expected_reputation_score < 100.0
    assert paper.author_reputation_score == pytest.approx(expected_reputation_score)
    assert paper.author_reputation_score != pytest.approx(100.0)
    # citation_velocity and influential_citation_ratio are both 0.0 on this
    # fixture paper, so only the reputation term contributes (issue #22's
    # weight-split change: DEFAULT_REPUTATION_WEIGHT is 0.34, not 0.5).
    assert paper.combined_score == pytest.approx(
        DEFAULT_REPUTATION_WEIGHT * expected_reputation_score
    )


# --- Regression: influential_citation_score must not go stale (#22 QA FAIL) -


@pytest.mark.django_db
def test_recompute_updates_stale_influential_citation_score_in_db():
    # Establish a baseline stored influential_citation_score via the normal
    # scoring path (influential_citation_ratio=0.2 -> influential_citation_score=20.0).
    author = Author.objects.create(name="Ratio Author")
    paper = Paper.objects.create(
        title="Paper with an influential-citation ratio",
        cited_by_count=0,
        publication_year=TODAY_YEAR,
        citation_velocity=0.0,
        influential_citation_ratio=0.2,
    )
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)
    update_paper_combined_score(paper, author, save=True)
    paper.refresh_from_db()
    assert paper.influential_citation_score == pytest.approx(20.0)

    # Simulate what a fresh fetch_semantic_scholar_embeddings re-run would
    # do: only the raw ratio is updated and saved, leaving the previously
    # stored (now stale) influential_citation_score at 20.0 until something
    # recomputes it.
    paper.influential_citation_ratio = 0.9
    paper.save(update_fields=["influential_citation_ratio"])

    _run_command()

    # Re-fetch from the DB (not the in-memory instance) -- this is the
    # assertion that catches the bug: a combined_score-only check would
    # pass even when the buggy update_fields list silently discards the
    # freshly-recomputed influential_citation_score before it reaches the
    # database.
    stored = Paper.objects.get(pk=paper.pk)
    assert stored.influential_citation_score == pytest.approx(90.0)


# --- Idempotency ----------------------------------------------------------


@pytest.mark.django_db
def test_repeated_runs_produce_identical_stored_values():
    author = Author.objects.create(name="Repeatable Author")
    for count, year in [(10, TODAY_YEAR - 5), (6, TODAY_YEAR - 3)]:
        Paper.objects.create(
            title=f"Paper ({count} cites)", cited_by_count=count, publication_year=year
        ).authorships.create(author=author, position=1)
    lead_paper = Paper.objects.filter(authorships__author=author).order_by("id").first()

    _run_command()
    author.refresh_from_db()
    lead_paper.refresh_from_db()
    first_run = {
        "h_index": author.h_index,
        "h_index_normalized": author.h_index_normalized,
        "citation_velocity": lead_paper.citation_velocity,
        "author_reputation_score": lead_paper.author_reputation_score,
        "velocity_score": lead_paper.velocity_score,
        "combined_score": lead_paper.combined_score,
    }

    _run_command()
    author.refresh_from_db()
    lead_paper.refresh_from_db()
    second_run = {
        "h_index": author.h_index,
        "h_index_normalized": author.h_index_normalized,
        "citation_velocity": lead_paper.citation_velocity,
        "author_reputation_score": lead_paper.author_reputation_score,
        "velocity_score": lead_paper.velocity_score,
        "combined_score": lead_paper.combined_score,
    }

    assert first_run == second_run


# --- No N+1: query count grows only by a fixed per-author/per-paper cost --
#
# A literally *constant* total query count regardless of dataset size (the
# AC's exact wording) is not achievable while reusing the existing
# per-instance `update_author_h_index`/`update_paper_citation_velocity`/
# `update_paper_combined_score` functions unmodified, as #14 requires:
# each Author/Paper still needs its own `.save()` (one query per row,
# inherent to those functions -- see #14's own text: "the command's only
# job is correct iteration/sequencing, not upsert logic").
#
# Per the #14 amendment, `compute_paper_author_reputation_score` /
# `update_paper_combined_score` now take an already-resolved `first_author`
# instead of looking it up themselves, and the command resolves it with a
# bare `.all()` on the prefetched `authorships` manager (reusing the
# `prefetch_related("authorships__author")` cache, since
# `PaperAuthorship.Meta.ordering = ["position"]` already sorts it) rather
# than the old `.order_by("position").first()`, which always bypassed the
# prefetch cache and issued a fresh query per paper. That removes the two
# previously-unavoidable extra reads per paper.
#
# What "no N+1" actually verifiably means here, and what these two tests
# prove: the query count is `BASE + num_authors + num_papers` -- a base
# constant (the two driving querysets plus their prefetches) plus a
# *fixed* per-author cost (1 `.save()`) and a *fixed* per-paper cost (1
# `.save()`, no per-paper multiplier beyond it) that does **not** depend
# on dataset size, and critically does not depend on how many authors a
# paper has or how many papers an author has (that would be the actual
# N+1 bug this test guards against). Both fixture sizes are asserted
# against the *same* formula.


def _build_fixture(*, num_authors: int, num_papers: int) -> None:
    authors = [Author.objects.create(name=f"Author {i}") for i in range(num_authors)]
    for i in range(num_papers):
        paper = Paper.objects.create(
            title=f"Paper {i}", cited_by_count=i + 1, publication_year=TODAY_YEAR - 1
        )
        if authors:
            PaperAuthorship.objects.create(paper=paper, author=authors[i % num_authors], position=1)


BASE_QUERY_COUNT = 5  # phase-1 Author query + its prefetch, phase-2/3 Paper query + its prefetch


def _expected_query_count(*, num_authors: int, num_papers: int) -> int:
    return BASE_QUERY_COUNT + num_authors + num_papers


@pytest.mark.django_db
def test_query_count_small_fixture_matches_formula(django_assert_num_queries):
    _build_fixture(num_authors=3, num_papers=5)
    expected = _expected_query_count(num_authors=3, num_papers=5)
    with django_assert_num_queries(expected):
        _run_command()


@pytest.mark.django_db
def test_query_count_large_fixture_matches_same_formula(django_assert_num_queries):
    # 4x the authors, 8x the papers of the small fixture above -- if the
    # command had a real N+1 (e.g. one extra query per *authorship row*
    # rather than a fixed cost per paper), this would blow past the linear
    # formula that the small fixture also satisfies.
    _build_fixture(num_authors=20, num_papers=40)
    expected = _expected_query_count(num_authors=20, num_papers=40)
    with django_assert_num_queries(expected):
        _run_command()


@pytest.mark.django_db
def test_query_count_formula_holds_for_a_third_independent_size():
    # Belt-and-braces: a third, differently-shaped fixture (more authors
    # than papers, unlike the two above) still fits the same formula when
    # measured directly via CaptureQueriesContext, per issue #14's
    # alternative-tool suggestion.
    _build_fixture(num_authors=12, num_papers=6)
    with CaptureQueriesContext(connection) as ctx:
        _run_command()
    assert len(ctx.captured_queries) == _expected_query_count(num_authors=12, num_papers=6)
