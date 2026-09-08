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


class SimilarPaperResultSchema(PaperSearchResultSchema):
    """One paper in a `GET /api/papers/{paper_id}/similar` result set.

    Extends (not duplicates) `PaperSearchResultSchema`'s shape, adding
    `similarity_score` -- per GitHub issue #23. `similarity_score` is
    `1 - cosine_distance` (i.e. cosine similarity itself: higher = more
    similar), returned at full float precision, deliberately *not*
    rescaled to the 0-100 range `author_reputation_score`/
    `velocity_score`/`combined_score` use, so it reads as "how similar"
    rather than being mistaken for another quality signal. Continues
    #17's transparency precedent (raw signal shown next to normalized/
    derived signal), applied here so a caller can see *why* a
    lower-`combined_score` result still outranks a higher-`combined_score`
    one that didn't make the candidate pool at all.
    """

    similarity_score: float


class SimilarPapersResponseSchema(Schema):
    """The `GET /api/papers/{paper_id}/similar` response envelope.

    No `count` field (unlike `PaperSearchResponseSchema`): `count` there
    exists to communicate truncation from a larger total match count;
    here `results` is never a truncated view of a larger *result* set in
    that sense (`len(results) <= RESULT_COUNT` is already
    self-describing), so a `count` field would be redundant.
    `source_paper_id` is included so a consumer that doesn't separately
    retain the requested id still has it on the response.
    """

    source_paper_id: int
    results: list[SimilarPaperResultSchema]
