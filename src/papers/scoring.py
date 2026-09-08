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


# --- Influential-citation ratio (issue #22) ---------------------------------
#
# The fraction of a paper's citations that Semantic Scholar flags as
# "highly influential" -- a third signal so a paper mostly cited in
# passing (related-work dumps) ranks lower than an equally-cited paper
# that genuinely shaped its field.
#
# Data source: Semantic Scholar's `citation_count`/`influential_citation_count`
# (via `semantic_scholar_client`, #20), consumed by
# `fetch_semantic_scholar_embeddings` (#21) and stored as
# `Paper.influential_citation_ratio` -- neither raw count is itself stored
# as a `Paper` column (see issue #22's Constraints).


def compute_influential_citation_ratio(
    influential_citation_count: int, citation_count: int
) -> float:
    """`influential_citation_count / citation_count`, or `0.0` if undefined.

    `citation_count == 0` is a zero-division guard, and also the correct
    fallback for "Semantic Scholar had no record at all" (the caller
    passes `0`/`0` in that case) -- mirroring `compute_citation_velocity`'s
    / `compute_h_index_normalized`'s existing `0.0`-on-undefined
    convention.
    """
    if citation_count == 0:
        return 0.0
    return influential_citation_count / citation_count


# --- Combined weighted score (issue #13, extended by #22) -------------------
#
# Combines the author-reputation signal (#11's `Author.h_index_normalized`),
# the citation-velocity signal (#12's `Paper.citation_velocity`), and the
# influential-citation-ratio signal (#22's `Paper.influential_citation_ratio`)
# into a single, transparent, per-paper `combined_score`: a plain weighted
# sum of three values that are each rescaled to a common 0-100 range first
# (a fixed linear clamp, not a corpus-relative or learned transform -- see
# issue #13's Constraints for why).
#
# Multi-author collapsing: the reputation component is taken from the
# *first* author only (`PaperAuthorship.position == 1`), not the max or
# average across all of a paper's authors -- matching the academic
# convention that first authorship carries primary credit (see issue #13's
# Acceptance criteria and #5's Constraints on `PaperAuthorship`).

# Absent real tuning data (same caveat #13's Constraints already carry for
# the original two weights), equal treatment across all three signals is
# the least-arbitrary default. Exact equal thirds (1/3 each) can't display
# as whole percentages summing to 100 (33+33+33 = 99); the spare 1% goes to
# DEFAULT_REPUTATION_WEIGHT (listed first in the formula) purely so the
# weight sentence reads 34%+33%+33% = 100% -- a cosmetic tie-break, not a
# claim that reputation matters more (see issue #22's Acceptance criteria).
DEFAULT_REPUTATION_WEIGHT = 0.34
DEFAULT_VELOCITY_WEIGHT = 0.33
DEFAULT_INFLUENTIAL_CITATION_WEIGHT = 0.33

# Best-guess constants grounded in typical observed ranges (not derived
# from real ingested data -- see issue #13's Constraints). Revisit once
# real data from #9/#34's ingestion is available.
H_INDEX_NORMALIZED_REFERENCE_MAX = 5.0
CITATION_VELOCITY_REFERENCE_MAX = 50.0


def normalize_h_index_score(h_index_normalized: float) -> float:
    """Rescale `h_index_normalized` to `0-100`, saturating at 100.

    A fixed linear clamp against `H_INDEX_NORMALIZED_REFERENCE_MAX`, not a
    corpus-relative min-max -- see issue #13's Constraints for why.
    """
    return min(h_index_normalized / H_INDEX_NORMALIZED_REFERENCE_MAX, 1.0) * 100


def normalize_velocity_score(citation_velocity: float) -> float:
    """Rescale `citation_velocity` to `0-100`, saturating at 100.

    A fixed linear clamp against `CITATION_VELOCITY_REFERENCE_MAX`, not a
    corpus-relative min-max -- see issue #13's Constraints for why.
    """
    return min(citation_velocity / CITATION_VELOCITY_REFERENCE_MAX, 1.0) * 100


def normalize_influential_citation_score(influential_citation_ratio: float) -> float:
    """Rescale `influential_citation_ratio` to `0-100`, saturating at 100.

    No fixed reference-max is needed here (unlike
    `h_index_normalized`/`citation_velocity`, which are unbounded above) --
    a genuine ratio is always `<= 1.0` since "influential" citations are a
    subset of all citations, so this is just the trivial `* 100`. The
    `min(..., 1.0)` clamp is kept anyway as a defensive guard against a
    malformed/inconsistent Semantic Scholar response (e.g.
    `influential_citation_count > citation_count`) producing a score above
    the 0-100 range other sub-signals guarantee.
    """
    return min(influential_citation_ratio, 1.0) * 100


def compute_paper_author_reputation_score(first_author: Author | None) -> float:
    """Normalized reputation score from an already-resolved first author.

    Takes the `Author` for the paper's position-1 `PaperAuthorship`
    directly (or `None` for a paper with zero authorships), rather than
    looking it up itself. The caller is responsible for resolving it --
    typically from a `.prefetch_related("authorships__author")`
    queryset, reading a bare `.all()` on the authorships manager (which
    reuses the prefetch cache and is already position-ordered per
    `PaperAuthorship.Meta.ordering`) rather than `.order_by(...)` or
    `.filter(...)`, which always bypass that cache and issue a fresh
    query. This keeps the function itself a plain, query-free
    computation, and moves the one query-shaped decision (how to find
    "first author" cheaply) to whichever caller already has the right
    data loaded (#14).
    """
    if first_author is None:
        return 0.0
    return normalize_h_index_score(first_author.h_index_normalized)


def update_paper_combined_score(
    paper: Paper, first_author: Author | None, save: bool = True
) -> Paper:
    """Recompute and store `author_reputation_score`/`velocity_score`/
    `influential_citation_score`/`combined_score` on `paper`.

    `first_author` is the `Author` for `paper`'s position-1 authorship
    (or `None`), resolved by the caller exactly as for
    `compute_paper_author_reputation_score` above. Still reads
    `paper.citation_velocity`, `paper.influential_citation_ratio`, and
    `first_author.h_index_normalized` as already stored -- it does not
    itself recompute those sub-signals (that stays #11/#12/#22's job;
    sequencing multiple papers/authors is #14's job). Convenience wrapper
    following the same shape as `update_author_h_index` /
    `update_paper_citation_velocity`. Set `save=False` to compute without
    writing to the database.
    """
    author_reputation_score = compute_paper_author_reputation_score(first_author)
    velocity_score = normalize_velocity_score(paper.citation_velocity)
    influential_citation_score = normalize_influential_citation_score(
        paper.influential_citation_ratio
    )
    combined_score = (
        DEFAULT_REPUTATION_WEIGHT * author_reputation_score
        + DEFAULT_VELOCITY_WEIGHT * velocity_score
        + DEFAULT_INFLUENTIAL_CITATION_WEIGHT * influential_citation_score
    )

    paper.author_reputation_score = author_reputation_score
    paper.velocity_score = velocity_score
    paper.influential_citation_score = influential_citation_score
    paper.combined_score = combined_score
    if save:
        paper.save(
            update_fields=[
                "author_reputation_score",
                "velocity_score",
                "influential_citation_score",
                "combined_score",
            ]
        )
    return paper
