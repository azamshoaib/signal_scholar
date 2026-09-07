"""HTTP calls to OpenAlex and parsing of its response shape into dataclasses.

Per GitHub issue #8: this issue was groomed without a live call to
OpenAlex, so its Constraints section flagged several assumptions as
unverified. Before writing this file, the following were checked against a
real, live response from `https://api.openalex.org/works/W2741809807` and
`https://api.openalex.org/works?search=...&cursor=*`:

- Keyword search uses `?search=<query>` (confirmed, not a `filter=`
  expression).
- Pagination is cursor-based via `?cursor=*` for the first page and the
  response's `meta.next_cursor` field for subsequent pages; `next_cursor`
  is `null` once there is nothing further to page through. Confirmed
  exactly as the issue guessed.
- Venue/source data lives at `primary_location.source`, **not** the older
  `host_venue` shape — confirmed against a live response, which had no
  `host_venue` key at all. `_parse_venue` below still checks `host_venue`
  as a defensive fallback in case an older/alternate endpoint response
  includes it, but the primary path is `primary_location.source`.
- `id` and `doi` come back as full URLs (`https://openalex.org/W...`,
  `https://doi.org/10...`), **not** short/bare forms — confirmed, and both
  need stripping. `openalex_id` fields are stripped to OpenAlex's short
  form (e.g. `W2741809807`) to match `Paper.openalex_id`'s existing
  convention (#5). `doi` is likewise stripped to the bare DOI (e.g.
  `10.7717/peerj.4375`) for the same "short form, not a URL" consistency,
  even though issue #8 didn't pin this down explicitly — `Paper.doi` has
  no documented convention either way, and storing the bare identifier
  rather than a resolvable URL matches the pattern used everywhere else.
- `abstract_inverted_index` is confirmed to be a word -> list-of-positions
  mapping (e.g. `{"Despite": [0], "growing": [1], "in": [3, 57, 73]}`),
  not plain text - matching the issue's guess and confirming why abstract
  reconstruction is best-effort (`_reconstruct_abstract` below degrades to
  `None` on any unexpected shape rather than raising).

This was checked with outbound network access available in the
implementation environment; if that ever changes, re-verify against
OpenAlex's public docs (https://docs.openalex.org/api-entities/works)
before trusting this file's assumptions blindly.
"""

from __future__ import annotations

from typing import Any

import requests

from .exceptions import OpenAlexClientError
from .types import OpenAlexAuthor, OpenAlexInstitution, OpenAlexVenue, OpenAlexWork

_BASE_URL = "https://api.openalex.org"
_TIMEOUT_SECONDS = 10
# OpenAlex's documented ceiling for `per-page` on list endpoints.
_MAX_PER_PAGE = 200


def _short_id(value: str | None) -> str | None:
    """Strip an OpenAlex full-URL ID down to its short form.

    `https://openalex.org/W2741809807` -> `W2741809807`. A value that is
    already short-form (no slash) round-trips unchanged, so this is safe
    to call on values of uncertain shape.
    """
    if not value:
        return None
    return value.rsplit("/", 1)[-1]


def _bare_doi(value: str | None) -> str | None:
    """Strip OpenAlex's `https://doi.org/...` DOI URL down to the bare DOI."""
    if not value:
        return None
    prefix = "https://doi.org/"
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def _reconstruct_abstract(inverted_index: Any) -> str | None:
    """Best-effort reconstruction of `abstract_inverted_index` into text.

    Per issue #8: a parsing miss degrades to `None`, it never raises. The
    real format is a mapping of word -> list of word positions; any other
    shape (missing, empty, wrong types) also yields `None`.
    """
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None

    try:
        position_to_word: dict[int, str] = {}
        for word, positions in inverted_index.items():
            for position in positions:
                position_to_word[position] = word

        if not position_to_word:
            return None

        max_position = max(position_to_word)
        words = [position_to_word.get(i, "") for i in range(max_position + 1)]
        text = " ".join(words).strip()
        return text or None
    except (TypeError, ValueError):
        return None


def _parse_institution(institution_json: Any) -> OpenAlexInstitution | None:
    if not isinstance(institution_json, dict):
        return None
    return OpenAlexInstitution(
        openalex_id=_short_id(institution_json.get("id")),
        name=institution_json.get("display_name") or "",
    )


def _parse_author(authorship_json: Any) -> OpenAlexAuthor | None:
    if not isinstance(authorship_json, dict):
        return None

    author_json = authorship_json.get("author") or {}
    institutions_json = authorship_json.get("institutions") or []

    institutions = [
        institution
        for institution in (_parse_institution(i) for i in institutions_json)
        if institution is not None
    ]

    return OpenAlexAuthor(
        openalex_id=_short_id(author_json.get("id")),
        name=author_json.get("display_name") or "",
        institutions=institutions,
    )


def _parse_venue(work_json: dict) -> OpenAlexVenue | None:
    primary_location = work_json.get("primary_location")
    source = primary_location.get("source") if isinstance(primary_location, dict) else None

    if not isinstance(source, dict):
        # Defensive fallback to the older shape OpenAlex has used before
        # (see this module's docstring) — not observed in the live
        # response checked while implementing this, but cheap to handle.
        source = work_json.get("host_venue")

    if not isinstance(source, dict):
        return None

    name = source.get("display_name")
    if not name:
        return None

    return OpenAlexVenue(openalex_id=_short_id(source.get("id")), name=name)


def _parse_work(work_json: dict) -> OpenAlexWork:
    """Parse one OpenAlex `work` JSON object into an `OpenAlexWork`.

    Raises `ValueError`/`TypeError`/`KeyError` on a shape so unexpected
    that a work can't be identified at all (e.g. missing `id`); callers
    catch these and re-raise as `OpenAlexClientError`.
    """
    if not isinstance(work_json, dict):
        raise TypeError(f"expected a work object (dict), got {type(work_json)!r}")

    openalex_id = _short_id(work_json.get("id"))
    if not openalex_id:
        raise ValueError("OpenAlex work is missing an 'id'")

    authorships = work_json.get("authorships") or []
    authors = [
        author for author in (_parse_author(a) for a in authorships) if author is not None
    ]

    return OpenAlexWork(
        openalex_id=openalex_id,
        title=work_json.get("title") or work_json.get("display_name") or "",
        publication_year=work_json.get("publication_year"),
        doi=_bare_doi(work_json.get("doi")),
        abstract=_reconstruct_abstract(work_json.get("abstract_inverted_index")),
        venue=_parse_venue(work_json),
        authors=authors,
    )


def _request(url: str, params: dict[str, Any]) -> tuple[dict, int]:
    """GET `url`, returning the decoded JSON body and status code.

    Raises `OpenAlexClientError` for any network failure, non-2xx
    response, or a body that isn't a JSON object — never lets a raw
    `requests` exception escape.
    """
    try:
        response = requests.get(url, params=params, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise OpenAlexClientError(
            f"Network error calling OpenAlex: {exc}", status_code=None
        ) from exc

    if not response.ok:
        raise OpenAlexClientError(
            f"OpenAlex returned HTTP {response.status_code} for {url}",
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenAlexClientError(
            f"OpenAlex returned a non-JSON response body: {exc}",
            status_code=response.status_code,
        ) from exc

    if not isinstance(data, dict):
        raise OpenAlexClientError(
            "OpenAlex returned an unexpected response body shape (not a JSON object)",
            status_code=response.status_code,
        )

    return data, response.status_code


def get_work(openalex_id: str) -> OpenAlexWork:
    """Fetch one work's full metadata by its OpenAlex short-form ID.

    `openalex_id` is the short form, e.g. `W2741809807`.
    """
    data, status_code = _request(f"{_BASE_URL}/works/{openalex_id}", params={})

    try:
        return _parse_work(data)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise OpenAlexClientError(
            f"Could not parse OpenAlex work response: {exc}", status_code=status_code
        ) from exc


def search_works(query: str, max_results: int = 25) -> list[OpenAlexWork]:
    """Search OpenAlex works by topic/keyword.

    Follows OpenAlex's cursor pagination internally, fetching successive
    pages until `max_results` items have been collected or OpenAlex
    reports no further pages (`meta.next_cursor` is `null`). Always
    returns one bounded `list[OpenAlexWork]`, never a generator, capped at
    `max_results` (issue #8's Constraints: #9 ingests a bounded set of
    papers per topic search, not an unbounded corpus crawl).
    """
    if max_results <= 0:
        return []

    works: list[OpenAlexWork] = []
    cursor: str | None = "*"

    while cursor and len(works) < max_results:
        per_page = min(_MAX_PER_PAGE, max_results - len(works))
        params = {"search": query, "per-page": per_page, "cursor": cursor}
        data, status_code = _request(f"{_BASE_URL}/works", params=params)

        try:
            page_results = data["results"]
            next_cursor = data["meta"]["next_cursor"]
        except (KeyError, TypeError) as exc:
            raise OpenAlexClientError(
                f"OpenAlex search response missing expected fields: {exc}",
                status_code=status_code,
            ) from exc

        if not isinstance(page_results, list):
            raise OpenAlexClientError(
                "OpenAlex search response 'results' was not a list",
                status_code=status_code,
            )

        try:
            for work_json in page_results:
                works.append(_parse_work(work_json))
                if len(works) >= max_results:
                    break
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise OpenAlexClientError(
                f"Could not parse an OpenAlex work in search results: {exc}",
                status_code=status_code,
            ) from exc

        if not page_results:
            break
        cursor = next_cursor

    return works
