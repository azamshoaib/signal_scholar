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

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.security import django_auth

from papers.models import Author, Follow, Institution, Paper
from papers.schemas import PaperSearchResponseSchema, SimilarPapersResponseSchema
from papers.services import (
    CANDIDATE_POOL_SIZE,
    DEFAULT_LIMIT,
    RESULT_COUNT,
    find_similar_papers,
    search_papers,
)

router = Router()


@router.get("/search", response=PaperSearchResponseSchema)
def search(
    request,
    q: str = Query(...),
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    year_min: int | None = Query(None),
    year_max: int | None = Query(None),
    velocity_min: float | None = Query(None, ge=0),
):
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

    Per GitHub issue #18, `year_min`/`year_max`/`velocity_min` are
    optional `AND`-combined filters narrowing the keyword search --
    `year_min`/`year_max` reject non-integers with Ninja's standard `422`
    for free, and `velocity_min`'s `ge=0` rejects a negative value with
    `422` before `search_papers` is ever called (so `search_papers`'s own
    `velocity_min < 0` check is unreachable from here -- it's exercised
    only by `papers.views.search`'s page path instead). A semantically
    invalid but well-typed combination (`year_min > year_max`) is caught
    below and turned into a `400`.
    """
    q = q.strip()
    try:
        results, count = search_papers(q, limit, year_min, year_max, velocity_min)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from None

    return {"results": results, "count": count}


@router.get("/papers/{paper_id}/similar", response=SimilarPapersResponseSchema)
def similar(request, paper_id: int):
    """Find papers similar to `paper_id`, re-ranked by quality.

    Per GitHub issue #23, this is the "paper-in, papers-out" entry point:
    given a paper already in the local database, return other
    locally-ingested papers that are semantically similar to it (#21's
    stored SPECTER v2 embeddings, via a pgvector cosine-distance query),
    re-ordered so a highly similar but low-quality paper ranks below a
    less similar but higher-quality one (#13/#22's `combined_score`) --
    a real two-stage "similar, then better" ranking, not a plain
    nearest-neighbor list. The actual query logic lives in
    `papers.services.find_similar_papers`, mirroring `search_papers`'s
    existing HTTP-shaping/query-logic split.

    A `paper_id` that doesn't correspond to any `Paper` row returns
    `404` (via `get_object_or_404`, mirroring `papers.views.detail`'s
    convention). A `paper_id` that exists but whose `embedding IS NULL`
    (never matched by Semantic Scholar -- see #21) returns `422`,
    deliberately distinct from the `404` above so a caller can
    distinguish "this paper doesn't exist" from "this paper exists but
    can't be compared yet" without parsing message text.
    """
    paper = get_object_or_404(Paper.objects.all(), pk=paper_id)
    if paper.embedding is None:
        raise HttpError(
            422,
            f"Paper {paper_id} has no stored embedding yet -- it cannot be "
            "compared for similarity.",
        )

    results = find_similar_papers(
        paper, candidate_pool_size=CANDIDATE_POOL_SIZE, result_count=RESULT_COUNT
    )

    return {"source_paper_id": paper.id, "results": results}


def _follow(request, **target) -> JsonResponse:
    """Shared `POST .../follow` body for the author/institution endpoints.

    `target` is `{"author": author}` or `{"institution": institution}` --
    whichever FK on `Follow` this call is for. Idempotent: a duplicate
    follow does not create a second row (`get_or_create`) and returns
    `200` instead of `201` per issue #25. Returns a raw `JsonResponse`
    (rather than relying on Ninja's `response=` schema) since the status
    code varies per call and Ninja requires every possible status to be
    pre-declared in a `response=` schema map.
    """
    _, created = Follow.objects.get_or_create(user=request.user, **target)
    status = 201 if created else 200
    return JsonResponse({"following": True, "created": created}, status=status)


def _unfollow(request, **target) -> HttpResponse:
    """Shared `DELETE .../follow` body for the author/institution endpoints.

    Idempotent: deleting a never-followed (but existing) target still
    returns `204` per issue #25 -- `404` is reserved for a nonexistent
    author/institution, checked by the caller before this runs.
    """
    Follow.objects.filter(user=request.user, **target).delete()
    return HttpResponse(status=204)


@router.post("/authors/{author_id}/follow", auth=django_auth)
def follow_author(request, author_id: int):
    """Follow `author_id`. See issue #25 for the full endpoint contract."""
    author = get_object_or_404(Author, pk=author_id)
    return _follow(request, author=author)


@router.delete("/authors/{author_id}/follow", auth=django_auth)
def unfollow_author(request, author_id: int):
    """Unfollow `author_id`. See issue #25 for the full endpoint contract."""
    author = get_object_or_404(Author, pk=author_id)
    return _unfollow(request, author=author)


@router.post("/institutions/{institution_id}/follow", auth=django_auth)
def follow_institution(request, institution_id: int):
    """Follow `institution_id`. See issue #25 for the full endpoint contract."""
    institution = get_object_or_404(Institution, pk=institution_id)
    return _follow(request, institution=institution)


@router.delete("/institutions/{institution_id}/follow", auth=django_auth)
def unfollow_institution(request, institution_id: int):
    """Unfollow `institution_id`. See issue #25 for the full endpoint contract."""
    institution = get_object_or_404(Institution, pk=institution_id)
    return _unfollow(request, institution=institution)
