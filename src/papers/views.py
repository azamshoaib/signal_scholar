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
"""

from __future__ import annotations

from django.shortcuts import render

from papers.services import search_papers


def search(request):
    q = request.GET.get("q", "")
    q_stripped = q.strip()

    results = None
    count = 0
    searched = bool(q_stripped)
    if searched:
        results, count = search_papers(q_stripped, limit=25)

    context = {
        "q": q,
        "results": results,
        "count": count,
        "searched": searched,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "papers/_results.html", context)

    return render(request, "papers/search.html", context)
