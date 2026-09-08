"""URL routing for the `papers` app's page views (as opposed to its API,
which lives under `/api/` via `papers.api`).

Per GitHub issue #16, page views belong in the `papers` app itself, not
piled into the project-level `signal_scholar/urls.py` -- the same
app-boundary precedent #15 set for API code. #17 will add another page
(`/papers/<id>/`) to this same file.

Per GitHub issue #24, `papers/<id>/similar/` is a dedicated route (not
`detail`'s existing route branching on `HX-Request`) -- see
`views.similar`'s own docstring for why.
"""

from __future__ import annotations

from django.urls import path

from papers import views

app_name = "papers"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("papers/<int:pk>/", views.detail, name="detail"),
    path("papers/<int:pk>/similar/", views.similar, name="similar"),
]
