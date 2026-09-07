"""Plain dataclasses returned by this client.

Per GitHub issue #8, these are the field names #9's ingestion command maps
directly onto `Paper`/`Author`/`Institution`/`Venue` (#5/#6) — no Django
import here, no coupling to that app's models.

Every `openalex_id` field holds OpenAlex's short form (e.g. `W2741809807`,
`A5048491430`, `I4200000001`), matching the convention `Paper.openalex_id`
et al. already use — never the full `https://openalex.org/...` URL
OpenAlex's API actually returns (verified against a live
`https://api.openalex.org/works/...` response while implementing this
issue; see `client.py`'s `_short_id`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OpenAlexInstitution:
    openalex_id: str | None
    name: str


@dataclass
class OpenAlexAuthor:
    openalex_id: str | None
    name: str
    # A list, not a single value: one work's authorship can list more than
    # one institution for an author. Collapsing to a single "primary"
    # institution is #9's job, not this client's (issue #8's Constraints).
    institutions: list[OpenAlexInstitution] = field(default_factory=list)


@dataclass
class OpenAlexVenue:
    openalex_id: str | None
    name: str


@dataclass
class OpenAlexWork:
    openalex_id: str
    title: str
    publication_year: int | None
    doi: str | None
    abstract: str | None
    venue: OpenAlexVenue | None
    # Ordered to match authorship position: index 0 is position 1,
    # matching `PaperAuthorship.position` (#5). OpenAlex's own
    # `authorships` array is already in this order, so this client
    # preserves list order rather than re-deriving it from the
    # `author_position` string field ("first"/"middle"/"last").
    authors: list[OpenAlexAuthor] = field(default_factory=list)
    # Per issue #34: OpenAlex always returns an integer `cited_by_count`
    # and an array `counts_by_year` (a rolling recent-years window, not
    # full lifetime history) — defaults here exist only for a work JSON
    # that's missing either key or has the wrong shape (see
    # `client._parse_work`'s defensive parsing).
    cited_by_count: int = 0
    counts_by_year: list[dict] = field(default_factory=list)
