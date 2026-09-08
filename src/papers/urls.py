"""URL routing for the `papers` app's page views (as opposed to its API,
which lives under `/api/` via `papers.api`).

Per GitHub issue #16, page views belong in the `papers` app itself, not
piled into the project-level `signal_scholar/urls.py` -- the same
app-boundary precedent #15 set for API code. #17 will add another page
(`/papers/<id>/`) to this same file.
"""

from __future__ import annotations

from django.urls import path

from papers import views

app_name = "papers"

urlpatterns = [
    path("search/", views.search, name="search"),
]
