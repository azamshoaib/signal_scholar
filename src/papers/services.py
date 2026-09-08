"""Shared, HTTP-agnostic query logic for the `papers` app.

Per GitHub issue #16, the filter/order/N+1-safe query logic that used to
live inline in `papers.api`'s Ninja view (#15) is extracted here so it can
be called both by that JSON API endpoint and by `papers.views.search`'s
HTML page (#16), without duplicating the query-building logic across two
callers.
"""

from __future__ import annotations

import logging
from typing import Callable

from django.db.models import Q
from pgvector.django import CosineDistance

from openalex_client import OpenAlexClientError, search_works
from papers import ingestion
from papers.models import Author, Paper
from papers.scoring import (
    DEFAULT_INFLUENTIAL_CITATION_WEIGHT,
    DEFAULT_REPUTATION_WEIGHT,
    DEFAULT_VELOCITY_WEIGHT,
    update_author_h_index,
    update_paper_citation_velocity,
    update_paper_combined_score,
)

logger = logging.getLogger(__name__)

# Capped modestly since this runs synchronously inside a search request --
# see `search_papers_with_live_fallback`'s docstring.
LIVE_FALLBACK_MAX_RESULTS = 15

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

# Per GitHub issue #23: fixed module-level constants, not query
# parameters -- see that issue's "Out of scope" for why making these
# configurable is deliberately deferred rather than built speculatively.
CANDIDATE_POOL_SIZE = 20
RESULT_COUNT = 10


def search_papers(
    q: str,
    limit: int = DEFAULT_LIMIT,
    year_min: int | None = None,
    year_max: int | None = None,
    velocity_min: float | None = None,
) -> tuple[list[dict], int]:
    """Search locally-ingested papers by keyword.

    This is substring matching (case-insensitive `icontains` against
    `title` OR `abstract`), not real search relevance -- there is no
    stemming, ranking, or tokenization. Real relevance ranking is filed
    as a follow-up: #36.

    `q` is matched only against `title`/`abstract`, never author names (a
    deliberate scope decision, not a bug -- see #15). Results are ordered
    by `-combined_score, id` (the `id` tiebreaker makes the order
    deterministic for equal `combined_score` rows). `limit` defaults to 25
    and is silently capped at `MAX_LIMIT` (100); the returned `count`
    reflects the total match count *before* `limit` truncation.

    Per GitHub issue #18, `year_min`/`year_max`/`velocity_min` are
    optional, additive `AND` filters applied on top of the keyword match,
    narrowing (not replacing) the #15/#16 search. All three default to
    `None`, meaning "no filter" -- a call with none of them supplied
    behaves exactly as before #18. "Field" filtering is out of scope for
    #18 (`Paper` has no classification column yet -- see #37).

    Raises `ValueError` for:
      - `q.strip()` empty -- the one piece of validation #15/#16 already
        had, unchanged. `q` stays required; #18 deliberately does not add
        a query-less "browse by filters alone" mode (see #18).
      - `year_min > year_max` (both given).
      - `velocity_min < 0`.
    This is deliberately a plain `ValueError`, not Ninja's `HttpError`,
    since this function has no knowledge of HTTP -- translating it into a
    400 response (or an inline page error) is the caller's job.
    """
    q = q.strip()
    if not q:
        raise ValueError("q must not be blank")
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ValueError("year_min must not be greater than year_max")
    if velocity_min is not None and velocity_min < 0:
        raise ValueError("velocity_min must not be negative")

    capped_limit = min(limit, MAX_LIMIT)

    queryset = (
        Paper.objects.select_related("venue")
        .prefetch_related("authorships__author")
        .filter(Q(title__icontains=q) | Q(abstract__icontains=q))
    )
    if year_min is not None:
        # `publication_year__gte` on a NULL `publication_year` is never
        # true under normal SQL NULL-comparison semantics, so a paper
        # with an unknown year is excluded whenever a year filter is
        # active -- intentional, not an oversight.
        queryset = queryset.filter(publication_year__gte=year_min)
    if year_max is not None:
        queryset = queryset.filter(publication_year__lte=year_max)
    if velocity_min is not None:
        queryset = queryset.filter(citation_velocity__gte=velocity_min)

    queryset = queryset.order_by("-combined_score", "id")
    count = queryset.count()

    results = []
    for paper in queryset[:capped_limit]:
        # Bare `.all()` on the prefetched `authorships` manager reuses the
        # prefetch cache (PaperAuthorship.Meta.ordering = ["position"]
        # already sorts it) -- never `.order_by()`/`.filter()`/`.first()`
        # here, which would bypass the cache and issue one query per
        # paper, reintroducing the N+1 bug #14 already had to fix once.
        authorships = list(paper.authorships.all())
        first_author_name = authorships[0].author.name if authorships else None
        results.append(
            {
                "id": paper.id,
                "title": paper.title,
                "publication_year": paper.publication_year,
                "doi": paper.doi,
                "venue_name": paper.venue.name if paper.venue else None,
                "first_author_name": first_author_name,
                "citation_velocity": paper.citation_velocity,
                "author_reputation_score": paper.author_reputation_score,
                "velocity_score": paper.velocity_score,
                "combined_score": paper.combined_score,
            }
        )

    return results, count


def _recompute_scores_for_papers(papers: list[Paper]) -> None:
    """Recompute h-index/velocity/combined-score for exactly `papers` and
    their authors -- a scoped version of `recompute_scores`'s whole-DB
    three-phase logic (issue #14), run against only the handful of rows
    a single live-fallback ingest just touched.

    Mirrors that command's ordering constraint exactly: every distinct
    author across `papers` gets `update_author_h_index` first, fully
    finished, before any paper's `update_paper_combined_score` runs --
    otherwise a paper's `author_reputation_score` would read a stale
    (pre-update) `h_index_normalized` off its first author. See
    `recompute_scores.py`'s module docstring for the full reasoning.
    """
    paper_ids = [paper.id for paper in papers]

    # Phase 1: every distinct author touched by this batch, deduplicated
    # via a set (a prolific author can appear as first author on more
    # than one of the newly-ingested papers).
    authors = Author.objects.filter(papers__id__in=paper_ids).distinct()
    for author in authors:
        update_author_h_index(author)

    # Phase 2+3: re-fetch (not reuse) the papers, after phase 1 has fully
    # committed, so each paper's first author's `h_index_normalized` is
    # read fresh -- same reasoning as `recompute_scores.py`.
    fresh_papers = Paper.objects.filter(id__in=paper_ids).prefetch_related(
        "authorships__author"
    )
    for paper in fresh_papers:
        authorships = list(paper.authorships.all())
        first_author = authorships[0].author if authorships else None
        update_paper_citation_velocity(paper, save=False)
        update_paper_combined_score(paper, first_author, save=False)
        paper.save(
            update_fields=[
                "citation_velocity",
                "author_reputation_score",
                "velocity_score",
                "influential_citation_score",
                "combined_score",
            ]
        )


def search_papers_with_live_fallback(
    q: str,
    limit: int = DEFAULT_LIMIT,
    year_min: int | None = None,
    year_max: int | None = None,
    velocity_min: float | None = None,
    on_fallback: Callable[[int], None] | None = None,
) -> tuple[list[dict], int]:
    """`search_papers`, but if the local catalog has nothing for `q`, try
    fetching it live from OpenAlex first.

    Without this, `search_papers` only ever finds what someone has
    already run `ingest_openalex` for -- a real visitor typing an
    arbitrary topic just gets "No papers found," even though OpenAlex
    almost certainly has matching papers. This closes that gap: on a
    zero-result local search, it calls OpenAlex's live search API for
    `q` (capped at `LIVE_FALLBACK_MAX_RESULTS`, since this runs
    synchronously inside the request -- there is no background job queue
    in this project's stack, see #28's Constraints), ingests whatever
    comes back through the exact same `papers.ingestion.ingest_works`
    path `ingest_openalex`/`poll_followed_authors` use, computes scores
    for just those newly-touched papers/authors
    (`_recompute_scores_for_papers`, above), and then re-runs the local
    query so the caller gets one consistent result shape either way.

    Raises the same `ValueError`s as `search_papers` (blank `q`,
    `year_min > year_max`, negative `velocity_min`) -- those are
    validation errors unrelated to "no local match yet," so they're
    allowed to propagate before any live call is attempted.

    If OpenAlex itself has nothing for `q`, or the live call fails for
    any reason (`OpenAlexClientError` -- network error, rate limit,
    malformed response), this falls back to the original empty local
    result rather than raising -- a slow/unavailable OpenAlex should
    degrade to "no results," never a 500.

    `on_fallback`, when given, is called with the number of works
    fetched live whenever the fallback actually fires (0 if OpenAlex
    also had nothing) -- callers can use this for a "results were just
    indexed" UI hint. Defaults to a no-op.

    Known limitation, not fixed here: `search_papers`'s own matching is
    naive `icontains` on `title`/`abstract` (#36), so it's possible for
    OpenAlex to return works relevant to `q` whose title/abstract don't
    literally contain that substring -- those get ingested and scored
    like everything else, but the re-run local query still won't surface
    them until a search that does match their text terms finds them.
    A single live-search call is also not rate-limited or cached beyond
    "once ingested, it's local from then on" -- repeated distinct
    zero-result queries each trigger a fresh OpenAlex call.
    """
    if on_fallback is None:
        on_fallback = lambda _work_count: None  # noqa: E731

    results, count = search_papers(q, limit, year_min, year_max, velocity_min)
    if count > 0:
        return results, count

    try:
        works = search_works(q.strip(), max_results=LIVE_FALLBACK_MAX_RESULTS)
    except OpenAlexClientError:
        logger.warning("Live OpenAlex search failed for q=%r", q, exc_info=True)
        works = []

    on_fallback(len(works))
    if not works:
        return results, count

    # Ingestion and scoring are a best-effort enhancement on top of an
    # already-valid (empty) search result -- any failure here (a DB
    # hiccup, a malformed upstream record, anything unanticipated) must
    # degrade back to that empty result, never surface as a 500 to a
    # search request. `search_works` above only guards its own call;
    # this guards everything after it.
    try:
        ingestion.ingest_works(works)
        touched_ids = [work.openalex_id for work in works if work.openalex_id]
        touched_papers = list(Paper.objects.filter(openalex_id__in=touched_ids))
        if touched_papers:
            _recompute_scores_for_papers(touched_papers)
        return search_papers(q, limit, year_min, year_max, velocity_min)
    except Exception:
        logger.exception(
            "Live-fallback ingest/score failed for q=%r after fetching %d works",
            q,
            len(works),
        )
        return results, count


def find_similar_papers(
    paper: Paper,
    candidate_pool_size: int = CANDIDATE_POOL_SIZE,
    result_count: int = RESULT_COUNT,
) -> list[dict]:
    """Find papers similar to `paper`, then re-rank that pool by quality.

    Per GitHub issue #23, this is a two-stage "similar, then better"
    query: first fetch the `candidate_pool_size` nearest neighbors to
    `paper.embedding` by cosine distance (via `pgvector.django`'s
    `CosineDistance`, which returns `1 - cosine_similarity` -- lower is
    more similar), excluding `paper` itself and any `Paper` with
    `embedding IS NULL`; then re-sort that pool by `combined_score`
    descending and return the top `result_count`. This is what makes the
    endpoint "similar but better" rather than a plain nearest-neighbor
    list: a highly similar but low-quality paper can rank below a less
    similar but higher-quality one, as long as both are in the pool.

    Callers are responsible for checking `paper.embedding is not None`
    before calling this -- exactly as `search_papers`'s `ValueError`-to-
    `HttpError` translation stays in `papers.api`, not here, the 404-vs-
    422 HTTP-shaping decision for a source paper with no embedding
    belongs in the caller, not this HTTP-agnostic function.

    The candidate-pool query orders by `(distance, id)` and the re-rank
    step orders by `(-combined_score, id)` -- both with an explicit `id`
    tiebreaker, matching `search_papers`'s deterministic-ordering
    convention so ordering assertions in tests aren't flaky.

    If fewer than `candidate_pool_size` other papers have a non-null
    `embedding`, the candidate pool is simply smaller (no error, no
    padding); if fewer than `result_count` candidates survive into the
    pool, all of them are returned (no error).

    Uses `.select_related("venue").prefetch_related("authorships__author")`
    on the candidate-pool query, with `first_author_name` resolved from
    the prefetched `authorships` manager's bare `.all()`, matching
    `search_papers`'s existing N+1-safe pattern exactly.
    """
    candidates = (
        Paper.objects.select_related("venue")
        .prefetch_related("authorships__author")
        .exclude(pk=paper.pk)
        .filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", paper.embedding))
        .order_by("distance", "id")[:candidate_pool_size]
    )

    pool = list(candidates)
    pool.sort(key=lambda candidate: (-candidate.combined_score, candidate.id))

    results = []
    for candidate in pool[:result_count]:
        # Bare `.all()` on the prefetched `authorships` manager reuses the
        # prefetch cache -- never `.order_by()`/`.filter()`/`.first()`
        # here, per `search_papers`'s same N+1-avoidance reasoning.
        authorships = list(candidate.authorships.all())
        first_author_name = authorships[0].author.name if authorships else None
        results.append(
            {
                "id": candidate.id,
                "title": candidate.title,
                "publication_year": candidate.publication_year,
                "doi": candidate.doi,
                "venue_name": candidate.venue.name if candidate.venue else None,
                "first_author_name": first_author_name,
                "citation_velocity": candidate.citation_velocity,
                "author_reputation_score": candidate.author_reputation_score,
                "velocity_score": candidate.velocity_score,
                "combined_score": candidate.combined_score,
                "similarity_score": 1 - candidate.distance,
            }
        )

    return results


def paper_score_breakdown(paper: Paper) -> dict:
    """Build the per-paper score-breakdown context for `_score_breakdown.html`.

    Per GitHub issue #27, this is the Python side of the same duplication
    the template extraction addresses: `views.detail` (#17) and
    `views.feed` (#27) both need the identical first-author/h_index-
    rounding/score-rounding logic, so it lives here exactly once.

    `paper.authorships__author` must already be prefetched by the caller
    (same N+1-safe convention `search_papers`/`find_similar_papers`
    already establish above) -- this function only ever does a bare
    `.all()` on the prefetched `authorships` manager, never
    `.order_by()`/`.filter()`, which would bypass the prefetch cache and
    issue a query per paper.

    Returns every key `_score_breakdown.html` needs except
    `weight_sentence`, which is a request-level constant (not per-paper)
    computed once by `weight_sentence()` below and passed in separately by
    the caller.
    """
    authorships = list(paper.authorships.all())
    if authorships:
        first_author = authorships[0].author
        first_author_name = first_author.name
        first_author_h_index_normalized = round(first_author.h_index_normalized, 2)
    else:
        first_author_name = "No authors on record"
        first_author_h_index_normalized = None

    return {
        "first_author_name": first_author_name,
        "first_author_h_index_normalized": first_author_h_index_normalized,
        "author_reputation_score": round(paper.author_reputation_score, 1),
        "citation_velocity": round(paper.citation_velocity, 2),
        "velocity_score": round(paper.velocity_score, 1),
        "influential_citation_ratio": round(paper.influential_citation_ratio, 2),
        "influential_citation_score": round(paper.influential_citation_score, 1),
        "combined_score": round(paper.combined_score, 1),
    }


def weight_sentence() -> str:
    """Build the sentence explaining `combined_score`'s weighting.

    Per GitHub issue #27, extracted verbatim from `views.detail`'s (#17)
    inline computation so `views.feed` can reuse it -- it reads the same
    `DEFAULT_REPUTATION_WEIGHT`/`DEFAULT_VELOCITY_WEIGHT`/
    `DEFAULT_INFLUENTIAL_CITATION_WEIGHT` constants #13 already defined,
    not a hardcoded copy that could go stale if those are retuned.
    """
    reputation_weight = round(DEFAULT_REPUTATION_WEIGHT * 100)
    velocity_weight = round(DEFAULT_VELOCITY_WEIGHT * 100)
    influential_citation_weight = round(DEFAULT_INFLUENTIAL_CITATION_WEIGHT * 100)
    return (
        f"Combined score = {reputation_weight}% author reputation "
        f"+ {velocity_weight}% citation velocity "
        f"+ {influential_citation_weight}% highly-influential-citation ratio."
    )
