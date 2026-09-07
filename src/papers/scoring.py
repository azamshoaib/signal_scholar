"""Academic-age-normalized h-index for an `Author`.

See GitHub issue #11. The goal (per the issue) is a reputation signal
that doesn't unfairly bury early-career researchers under senior PIs who
have simply had more career-years to accumulate citations: a raw h-index
divided by "academic age" (years since first publication).

Data source: `Paper.cited_by_count` and `Paper.publication_year`, reached
from an `Author` via the `PaperAuthorship` through-model (`Author.papers`,
the reverse of `Paper.authors`) — not the `Citation` edge model, which
models a different, still-future need (cross-field citation-diversity;
see issue #11's Constraints).

These functions are deliberately plain — they take already-fetched values
(lists of ints) or an `Author` instance and do no I/O beyond the one query
each DB-facing function issues, so they're easy to unit test with
hand-built fixtures and easy to reuse from a future recompute command
(#14).
"""

from __future__ import annotations

import datetime

from papers.models import Author, Paper


def compute_h_index(cited_by_counts: list[int]) -> int:
    """Standard h-index: the largest `h` such that at least `h` of the
    given citation counts are each `>= h`.

    Concretely: sort descending; `h` is the largest 1-indexed position
    `i` where the i-th value is `>= i`.
    """
    counts_desc = sorted(cited_by_counts, reverse=True)
    h_index = 0
    for position, count in enumerate(counts_desc, start=1):
        if count >= position:
            h_index = position
        else:
            break
    return h_index


def compute_academic_age(
    publication_years: list[int | None],
    current_year: int | None = None,
) -> int | None:
    """`current_year - first_publication_year + 1`, floored to 1.

    `first_publication_year` is the minimum non-null value in
    `publication_years`. Returns `None` (undefined) if every value is
    `None` — the caller decides the fallback for that case, since a
    "0" or "1" here would silently pretend a real academic age was
    known.

    `current_year` defaults to the year at call time and is never
    stored, so a later recompute naturally ages every author (#14/#28).
    """
    known_years = [year for year in publication_years if year is not None]
    if not known_years:
        return None

    if current_year is None:
        current_year = datetime.date.today().year

    first_publication_year = min(known_years)
    age = current_year - first_publication_year + 1
    # Floored to 1: academic age is never zero or negative, even for a
    # first-publication-this-year author or bad data with a future year.
    return max(age, 1)


def compute_h_index_normalized(h_index: int, academic_age: int | None) -> float:
    """`h_index / academic_age`, or `0.0` if academic age is undefined.

    Academic age is `None` when an author has no paper with a known
    `publication_year` — a defined fallback (not an error), per issue
    #11. This is the one case where `h_index` and `h_index_normalized`
    visibly diverge: `h_index` may be nonzero while the normalized
    value is zeroed.
    """
    if academic_age is None:
        return 0.0
    return h_index / academic_age


def compute_author_h_index_scores(
    author: Author, current_year: int | None = None
) -> tuple[int, float]:
    """Compute `(h_index, h_index_normalized)` for `author` from their papers.

    Reads `cited_by_count`/`publication_year` from `author.papers.all()`
    (via `PaperAuthorship` -> `Paper`, added by #34). An author with zero
    papers gets `(0, 0.0)`.
    """
    papers = list(author.papers.all())
    cited_by_counts = [paper.cited_by_count for paper in papers]
    publication_years = [paper.publication_year for paper in papers]

    h_index = compute_h_index(cited_by_counts)
    academic_age = compute_academic_age(publication_years, current_year=current_year)
    h_index_normalized = compute_h_index_normalized(h_index, academic_age)

    return h_index, h_index_normalized


def update_author_h_index(
    author: Author, current_year: int | None = None, save: bool = True
) -> Author:
    """Recompute and store `h_index`/`h_index_normalized` on `author`.

    Convenience wrapper around `compute_author_h_index_scores` for actual
    use (ingestion, admin actions, a future recompute command #14). Set
    `save=False` to compute without writing to the database.
    """
    h_index, h_index_normalized = compute_author_h_index_scores(
        author, current_year=current_year
    )
    author.h_index = h_index
    author.h_index_normalized = h_index_normalized
    if save:
        author.save(update_fields=["h_index", "h_index_normalized"])
    return author


# --- Per-paper citation velocity (issue #12) --------------------------------
#
# A "citations per year since publication" signal per plan.md's Impact
# Signals section, so a good recent paper isn't buried under lifetime-total
# comparisons against much older papers just because it hasn't had time to
# accumulate citations yet.
#
# Data source: `Paper.cited_by_count` and `Paper.publication_year` (both
# added by #34) — not the `Citation` edge model (see #11's Constraints for
# why) and not `Paper.counts_by_year`, whose bounded recent-years window
# can't answer "since publication" for an old paper (a separate,
# recent-momentum signal is tracked as #35).


def compute_years_since_publication(
    publication_year: int | None,
    current_year: int | None = None,
) -> int | None:
    """`current_year - publication_year`, floored to 1. `None` if unknown.

    Deliberately does not use `compute_academic_age`'s `+ 1` offset:
    that function answers "how many career-years has this author
    touched" (first year counts as year 1); this one answers "how much
    elapsed time has this specific paper had to accumulate citations",
    which is `current_year - publication_year` with no +1 — a paper
    published last year has had ~1 year, not 2. The floor-to-1 is the
    only thing carried over from `compute_academic_age`: it keeps a
    same-year (or bad-data future-dated) paper from causing a
    division-by-zero or an inflated velocity from a sub-1 divisor.

    `current_year` defaults to the year at call time and is never
    stored, so a later recompute naturally ages every paper (#14/#28).
    """
    if publication_year is None:
        return None

    if current_year is None:
        current_year = datetime.date.today().year

    years = current_year - publication_year
    return max(years, 1)


def compute_citation_velocity(
    cited_by_count: int, years_since_publication: int | None
) -> float:
    """`cited_by_count / years_since_publication`, or `0.0` if undefined.

    `years_since_publication` is `None` when `publication_year` is
    unknown — a defined fallback (not an error), per issue #12,
    mirroring `compute_h_index_normalized`'s `0.0` fallback (#11). This
    is the one case where `cited_by_count` (which may be nonzero) and
    `citation_velocity` visibly diverge.
    """
    if years_since_publication is None:
        return 0.0
    return cited_by_count / years_since_publication


def compute_paper_citation_velocity(
    paper: Paper, current_year: int | None = None
) -> float:
    """Compute `citation_velocity` for `paper` from its own fields.

    Reads `paper.cited_by_count`/`paper.publication_year` directly (both
    added by #34) — no I/O beyond the already-fetched instance.
    """
    years_since_publication = compute_years_since_publication(
        paper.publication_year, current_year=current_year
    )
    return compute_citation_velocity(paper.cited_by_count, years_since_publication)


def update_paper_citation_velocity(
    paper: Paper, current_year: int | None = None, save: bool = True
) -> Paper:
    """Recompute and store `citation_velocity` on `paper`.

    Convenience wrapper around `compute_paper_citation_velocity` for
    actual use (ingestion, admin actions, a future recompute command
    #14). Set `save=False` to compute without writing to the database.
    """
    paper.citation_velocity = compute_paper_citation_velocity(
        paper, current_year=current_year
    )
    if save:
        paper.save(update_fields=["citation_velocity"])
    return paper
