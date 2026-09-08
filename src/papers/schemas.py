"""Django Ninja `Schema` classes for the `papers` app's API responses.

Per GitHub issue #15, this holds the response schemas for `GET /api/search`
(`papers.api.search_papers`). Later issues (#17, #18, #19's backing
changes, #23) add their own schemas here too, per #15's Constraints on
keeping app-specific API code out of `signal_scholar`.
"""

from __future__ import annotations

from ninja import Schema


class PaperSearchResultSchema(Schema):
    """One paper in a search result set.

    Field selection and null semantics are the exact contract #15 defines
    for #16 (search UI) and #19 (weights slider) to build against.
    `author_reputation_score` and `velocity_score` are included alongside
    `combined_score` so #19 can recombine them client-side without a
    full recompute. `abstract` is deliberately excluded -- see #15.
    """

    id: int
    title: str
    publication_year: int | None
    doi: str | None
    venue_name: str | None
    first_author_name: str | None
    citation_velocity: float
    author_reputation_score: float
    velocity_score: float
    combined_score: float


class PaperSearchResponseSchema(Schema):
    """The `GET /api/search` response envelope.

    A single JSON object rather than a bare array, deliberately -- so
    `count` (and any future metadata, e.g. an echoed `q`) can be added
    later without a breaking top-level shape change for consumers.
    """

    results: list[PaperSearchResultSchema]
    count: int
