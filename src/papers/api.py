"""Django Ninja API views for the `papers` app.

Per GitHub issue #15, paper-related endpoints live here (not in
`signal_scholar/api.py`) to keep app-specific API code out of the
project-level package. `router` is mounted at the same, empty prefix as
`/health` in `signal_scholar/api.py`, so `@router.get("/search")` below
resolves to exactly `/api/search`.

Per GitHub issue #16, the actual filter/order/N+1-safe query logic has
been extracted into `papers.services.search_papers` (an HTTP-agnostic
function shared with `papers.views.search`, the HTML search page) --
this view is now a thin wrapper that adapts that function's `ValueError`
into Ninja's `HttpError` and shapes the JSON response.
"""

from __future__ import annotations

from ninja import Query, Router
from ninja.errors import HttpError

from papers.schemas import PaperSearchResponseSchema
from papers.services import DEFAULT_LIMIT, search_papers

router = Router()


@router.get("/search", response=PaperSearchResponseSchema)
def search(request, q: str = Query(...), limit: int = Query(DEFAULT_LIMIT, ge=1)):
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
    try:
        results, count = search_papers(q, limit)
    except ValueError:
        raise HttpError(400, "q must not be blank") from None

    return {"results": results, "count": count}
