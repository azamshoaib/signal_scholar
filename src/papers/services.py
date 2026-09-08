"""Shared, HTTP-agnostic query logic for the `papers` app.

Per GitHub issue #16, the filter/order/N+1-safe query logic that used to
live inline in `papers.api`'s Ninja view (#15) is extracted here so it can
be called both by that JSON API endpoint and by `papers.views.search`'s
HTML page (#16), without duplicating the query-building logic across two
callers.
"""

from __future__ import annotations

from django.db.models import Q

from papers.models import Paper

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def search_papers(q: str, limit: int = DEFAULT_LIMIT) -> tuple[list[dict], int]:
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

    Raises `ValueError` if `q.strip()` is empty -- the one piece of
    validation shared by both callers. This is deliberately a plain
    `ValueError`, not Ninja's `HttpError`, since this function has no
    knowledge of HTTP -- translating it into a 400 response is the
    caller's job.
    """
    q = q.strip()
    if not q:
        raise ValueError("q must not be blank")

    capped_limit = min(limit, MAX_LIMIT)

    queryset = (
        Paper.objects.select_related("venue")
        .prefetch_related("authorships__author")
        .filter(Q(title__icontains=q) | Q(abstract__icontains=q))
        .order_by("-combined_score", "id")
    )
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
