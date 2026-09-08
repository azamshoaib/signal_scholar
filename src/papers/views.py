"""Django page views for the `papers` app (as opposed to its JSON API,
which lives in `papers.api`).

Per GitHub issue #16, `search` renders the topic search page. It is a
single view handling both the full-page load (`GET /search/` or
`GET /search/?q=...` typed directly in the browser, or a bookmarked/
shared link) and the HTMX partial swap triggered by submitting the
search form (`GET /search/?q=...` with the `HX-Request: true` header) --
both branch on the same query-param parsing and call the same
`papers.services.search_papers` function, so that logic isn't duplicated
across two view functions.

Per GitHub issue #18, `search` also parses `year_min`/`year_max`/
`velocity_min` from `request.GET` (a small int/float-parsing helper
below treats an unparseable value as "not provided" rather than an
error, since these only reach the server via a hand-edited URL -- the
number inputs already constrain normal browser use) and passes them
through to `papers.services.search_papers`. A syntactically valid but
semantically invalid combination (e.g. `year_min > year_max`) raises
`ValueError` from that call, which is rendered as inline error text in
`papers/_results.html` instead of a result list.

Per GitHub issue #17, `detail` renders a single paper's detail page,
including a transparency breakdown of the `papers.scoring` sub-signals
that produced its `combined_score`. Unlike `search`, it builds its
context directly in the view rather than via a `papers.services`
function -- nothing else in the app currently needs the same query
(see issue #17's Constraints on why extracting a service now would be
speculative generality), and it is a single plain `GET` with no HTMX
partial to render.

Per GitHub issue #24, `similar` renders the "similar but better" papers
HTMX partial for `detail.html`'s button. It is a dedicated route (not
`detail`'s route branching on `HX-Request`), since -- unlike
`/search/?q=...` -- this URL has no full-page/bookmarkable counterpart:
it only ever appears as a fragment inside the detail page. It calls
`papers.services.find_similar_papers` directly (never `papers.api`),
exactly as #23's own Constraints anticipated, and checks
`paper.embedding is None` itself before calling it, since that
HTTP-agnostic function assumes its caller already did.

Per GitHub issue #27, `feed` renders a signed-in user's personalized
`/feed/` page: papers connected to the authors/institutions they follow
(#25's `Follow` model), newest first. It reuses the score-breakdown
extraction this same issue pulled out of `detail`'s former inline
computation -- `papers.services.paper_score_breakdown`/`weight_sentence`
-- so `detail` and `feed` share exactly one implementation of that logic
instead of two. Gated with `@login_required` (#42's `LOGIN_URL`/
`LOGIN_REDIRECT_URL`).
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, render

from papers.models import Follow, Paper
from papers.scoring import DEFAULT_REPUTATION_WEIGHT, DEFAULT_VELOCITY_WEIGHT
from papers.services import (
    DEFAULT_LIMIT,
    find_similar_papers,
    paper_score_breakdown,
    search_papers,
    weight_sentence,
)


def _parse_optional_number(raw: str | None, cast):
    """Parse a raw `request.GET` string with `cast` (`int` or `float`).

    Returns `None` for a missing/blank value *or* one `cast` can't parse
    -- per #18, a malformed value in a hand-edited URL degrades to "not
    provided" rather than surfacing a raw validation error on the page.
    """
    if raw is None or raw.strip() == "":
        return None
    try:
        return cast(raw)
    except ValueError:
        return None


def search(request):
    q = request.GET.get("q", "")
    q_stripped = q.strip()

    year_min = _parse_optional_number(request.GET.get("year_min"), int)
    year_max = _parse_optional_number(request.GET.get("year_max"), int)
    velocity_min = _parse_optional_number(request.GET.get("velocity_min"), float)

    results = None
    count = 0
    error = None
    searched = bool(q_stripped)
    if searched:
        try:
            results, count = search_papers(
                q_stripped,
                limit=25,
                year_min=year_min,
                year_max=year_max,
                velocity_min=velocity_min,
            )
        except ValueError as exc:
            error = str(exc)

    # Per #19: the slider's starting position always matches #13's actual
    # current default weight, rather than a hardcoded copy of today's 0.5
    # that would silently go stale if #13's constants are ever retuned.
    default_reputation_weight_pct = round(DEFAULT_REPUTATION_WEIGHT * 100)
    default_velocity_weight_pct = round(DEFAULT_VELOCITY_WEIGHT * 100)

    context = {
        "q": q,
        "year_min": year_min,
        "year_max": year_max,
        "velocity_min": velocity_min,
        "results": results,
        "count": count,
        "searched": searched,
        "error": error,
        "default_reputation_weight_pct": default_reputation_weight_pct,
        "default_velocity_weight_pct": default_velocity_weight_pct,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "papers/_results.html", context)

    return render(request, "papers/search.html", context)


def detail(request, pk):
    # `select_related`/`prefetch_related` before `get_object_or_404`,
    # matching the N+1-safe pattern `papers.services.search_papers`
    # already established -- the page needs the venue and every author,
    # not just the first, so both must be loaded up front.
    queryset = Paper.objects.select_related("venue").prefetch_related(
        "authorships__author"
    )
    paper = get_object_or_404(queryset, pk=pk)

    # Bare `.all()` on the prefetched `authorships` manager reuses the
    # prefetch cache (PaperAuthorship.Meta.ordering = ["position"]
    # already sorts it) -- never `.order_by()`/`.filter()` here, per
    # `papers.services.search_papers`'s same reasoning.
    authorships = list(paper.authorships.all())
    authors = [authorship.author for authorship in authorships]

    context = {
        "paper": paper,
        "authors": authors,
        "weight_sentence": weight_sentence(),
        **paper_score_breakdown(paper),
    }

    return render(request, "papers/detail.html", context)


def similar(request, pk):
    # A single `get_object_or_404` lookup, no `select_related`/
    # `prefetch_related` -- this view never renders the *source* paper's
    # own venue/authors, only the candidate results `find_similar_papers`
    # already returns fully assembled as plain dicts.
    paper = get_object_or_404(Paper, pk=pk)

    if paper.embedding is None:
        results = None
    else:
        results = find_similar_papers(paper)

    context = {"results": results}

    return render(request, "papers/_similar.html", context)


@login_required
def feed(request):
    # Per #27: collect the user's followed author/institution ids in two
    # queries, then a single `Q`-OR filter across the `authorships` join
    # finds papers matching either. `.distinct()` is required because that
    # `Q`-OR can multiply rows -- e.g. a paper with two followed authors
    # would otherwise appear twice.
    followed_author_ids = Follow.objects.filter(
        user=request.user, author__isnull=False
    ).values_list("author_id", flat=True)
    followed_institution_ids = Follow.objects.filter(
        user=request.user, institution__isnull=False
    ).values_list("institution_id", flat=True)

    # Empty state (a) ("follows no one at all") is distinguished from
    # empty state (b) ("follows someone, but they have no papers yet") by
    # this existence check, evaluated independently of the papers query
    # below.
    follows_anyone = Follow.objects.filter(user=request.user).exists()

    # `select_related`/`prefetch_related` matches `detail`/`search_papers`'s
    # existing N+1-safe pattern. Ordered by `publication_year` descending
    # with `nulls_last=True` (via `F(...).desc(nulls_last=True)`) rather
    # than a naive `-publication_year` -- Postgres's default `DESC` NULL
    # placement is NULLS FIRST, which would otherwise sort unknown-year
    # papers to the top and wrongly claim them as "newest". `-id` is the
    # deterministic tiebreak for same-year papers, matching
    # `search_papers`'s existing `id`-tiebreak convention.
    queryset = (
        Paper.objects.select_related("venue")
        .prefetch_related("authorships__author")
        .filter(
            Q(authorships__author_id__in=followed_author_ids)
            | Q(authorships__author__institution_id__in=followed_institution_ids)
        )
        .distinct()
        .order_by(F("publication_year").desc(nulls_last=True), "-id")
    )
    count = queryset.count()
    papers = list(queryset[:DEFAULT_LIMIT])

    # The full score breakdown is rendered per card (not just
    # `combined_score`), reusing `_score_breakdown.html`. `weight_sentence`
    # is request-level constant, computed once and shared by every card's
    # include, not recomputed per paper.
    shared_weight_sentence = weight_sentence()
    items = [
        {"paper": paper, "breakdown": paper_score_breakdown(paper)} for paper in papers
    ]

    context = {
        "follows_anyone": follows_anyone,
        "items": items,
        "count": count,
        "weight_sentence": shared_weight_sentence,
    }

    return render(request, "papers/feed.html", context)
