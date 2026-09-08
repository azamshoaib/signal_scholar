"""Django Ninja API views for the `papers` app.

Per GitHub issue #15, paper-related endpoints live here (not in
`signal_scholar/api.py`) to keep app-specific API code out of the
project-level package. `router` is mounted at the same, empty prefix as
`/health` in `signal_scholar/api.py`, so `@router.get("/search")` below
resolves to exactly `/api/search`.
"""

from __future__ import annotations

from django.db.models import Q
from ninja import Query, Router
from ninja.errors import HttpError

from papers.models import Paper
from papers.schemas import PaperSearchResponseSchema

router = Router()

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


@router.get("/search", response=PaperSearchResponseSchema)
def search_papers(request, q: str = Query(...), limit: int = Query(DEFAULT_LIMIT, ge=1)):
    """Search locally-ingested papers by keyword.

    This is substring matching (case-insensitive `icontains` against
    `title` OR `abstract`), not real search relevance -- there is no
    stemming, ranking, or tokenization. Real relevance ranking is filed
    as a follow-up: #36.

    `q` is required and is matched only against `title`/`abstract`, never
    author names (a deliberate scope decision, not a bug -- see #15).
    Results are ordered by `-combined_score, id` (the `id` tiebreaker
    makes the order deterministic for equal `combined_score` rows).
    `limit` defaults to 25 and is silently capped at 100; `count` in the
    response reflects the total match count *before* `limit` truncation.
    """
    q = q.strip()
    if not q:
        raise HttpError(400, "q must not be blank")

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

    return {"results": results, "count": count}
