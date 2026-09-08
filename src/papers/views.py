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
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404, render

from papers.models import Paper
from papers.scoring import DEFAULT_REPUTATION_WEIGHT, DEFAULT_VELOCITY_WEIGHT
from papers.services import search_papers


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

    if authorships:
        first_author = authorships[0].author
        first_author_name = first_author.name
        first_author_h_index_normalized = round(first_author.h_index_normalized, 2)
    else:
        first_author_name = "No authors on record"
        first_author_h_index_normalized = None

    reputation_weight = round(DEFAULT_REPUTATION_WEIGHT * 100)
    velocity_weight = round(DEFAULT_VELOCITY_WEIGHT * 100)
    weight_sentence = (
        f"Combined score = {reputation_weight}% author reputation "
        f"+ {velocity_weight}% citation velocity."
    )

    context = {
        "paper": paper,
        "authors": authors,
        "first_author_name": first_author_name,
        "first_author_h_index_normalized": first_author_h_index_normalized,
        "author_reputation_score": round(paper.author_reputation_score, 1),
        "citation_velocity": round(paper.citation_velocity, 2),
        "velocity_score": round(paper.velocity_score, 1),
        "combined_score": round(paper.combined_score, 1),
        "weight_sentence": weight_sentence,
    }

    return render(request, "papers/detail.html", context)
