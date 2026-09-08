"""HTTP calls to Semantic Scholar and parsing of its response shape into
`SemanticScholarPaper`.

Per GitHub issue #20, the following was confirmed live during that issue's
grooming pass (2026-09-08), against
`https://api.semanticscholar.org/graph/v1/paper/DOI:10.1038/nature12373`
and `.../paper/batch`, unauthenticated:

- Unauthenticated access works, but the rate limit is tight and shared
  globally (not per-IP) — repeated single-paper GETs spaced 4-6 seconds
  apart hit HTTP 429 more often than they succeeded, and no `Retry-After`
  header is sent. This client does not retry (see issue #20's Out of
  scope / follow-up #38) — a 429 is surfaced to the caller as a
  `SemanticScholarClientError` with `status_code=429`.
- DOI is the lookup key: `GET /paper/DOI:<bare-doi>` (no `DOI:` prefix or
  URL from the caller — this module adds the prefix internally).
  Semantic Scholar's own `paperId` has no relationship to OpenAlex's
  `W...` IDs, so it is kept on `SemanticScholarPaper` for
  logging/debugging only, never as a join key.
- `embedding` has two model versions; the *default* unqualified
  `fields=embedding` returns the older `specter_v1`. This client requests
  `fields=embedding.specter_v2` explicitly to get the newer model. Both
  versions come back in the identical `{"model", "vector"}` shape and are
  768-dimensional.
- `influentialCitationCount` and `citationCount` are plain top-level
  integers.
- `tldr` is `{"model": ..., "text": "..."}` when present, and Semantic
  Scholar's docs say it can be `null` — parsed defensively here, same as
  everything else in this file.
- `fields=doi` is invalid (`doi` is only reachable via
  `externalIds.DOI`) — confirmed live to 400.
- A single `fields=` query string works identically across the
  single-GET and batch-POST endpoints.
- `POST /paper/batch` returns unmatched IDs as positional `null`s in the
  response array (not an error, not an omitted element) — confirmed live
  with a 2-element batch. `get_papers` mirrors that shape back to its
  caller as `None` at that index.
- Error-body shape is not consistent across status codes (a 429 body has
  `{"message", "code"}`, a 404/400 body has `{"error"}`) — this file, like
  #8's `_request`, does not try to parse the error body for a message; it
  treats any non-2xx uniformly and attaches `status_code`.

This was checked with outbound network access available in the
implementation environment; if that ever changes, re-verify against
Semantic Scholar's public docs (https://api.semanticscholar.org/api-docs/)
before trusting this file's assumptions blindly.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .exceptions import SemanticScholarClientError
from .types import SemanticScholarPaper

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_TIMEOUT_SECONDS = 10
_API_KEY_ENV_VAR = "SEMANTIC_SCHOLAR_API_KEY"
# Per issue #20's Constraints: `embedding.specter_v2` must be requested
# explicitly, since the bare `embedding` field returns the older v1 model
# in the identical shape (no signal that anything is wrong). `doi` is
# invalid as a field name; the DOI is only reachable via `externalIds`.
_FIELDS = "title,externalIds,citationCount,influentialCitationCount,tldr,embedding.specter_v2"


def _headers() -> dict[str, str]:
    """Build request headers, adding `x-api-key` when an API key is set.

    Per issue #20: `SEMANTIC_SCHOLAR_API_KEY`, when set, is sent as
    Semantic Scholar's documented `x-api-key` auth header. When unset, no
    such header is sent and requests go out unauthenticated, exactly as
    verified live in this issue's grooming pass.
    """
    api_key = os.environ.get(_API_KEY_ENV_VAR)
    if api_key:
        return {"x-api-key": api_key}
    return {}


def _parse_citation_count(paper_json: dict, key: str) -> int:
    """Parse an integer citation-style field, defaulting to `0`.

    Mirrors #34's `_parse_cited_by_count` exactly (including excluding
    `bool`, a subclass of `int` in Python), applied to both
    `citationCount` and `influentialCitationCount` per issue #20.
    """
    value = paper_json.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _parse_doi(paper_json: dict) -> str | None:
    external_ids = paper_json.get("externalIds")
    if not isinstance(external_ids, dict):
        return None
    doi = external_ids.get("DOI")
    return doi if isinstance(doi, str) and doi else None


def _parse_embedding(paper_json: dict) -> list[float] | None:
    """Parse the `embedding.specter_v2` vector, degrading to `None`.

    `None` when the field is absent/`null`, or when it's present but
    doesn't have the expected `{"vector": [...]}` shape with numeric
    entries — this client never raises over a missing/malformed
    embedding, matching this file's/#8's defensive-parsing pattern.
    """
    embedding_json = paper_json.get("embedding")
    if not isinstance(embedding_json, dict):
        return None

    vector = embedding_json.get("vector")
    if not isinstance(vector, list) or not vector:
        return None

    try:
        return [float(component) for component in vector]
    except (TypeError, ValueError):
        return None


def _parse_tldr(paper_json: dict) -> str | None:
    tldr_json = paper_json.get("tldr")
    if not isinstance(tldr_json, dict):
        return None
    text = tldr_json.get("text")
    return text if isinstance(text, str) and text else None


def _parse_paper(paper_json: Any) -> SemanticScholarPaper:
    """Parse one Semantic Scholar `paper` JSON object.

    Raises `ValueError`/`TypeError` on a shape so unexpected that a paper
    can't be identified at all (e.g. missing `paperId`); callers catch
    these and re-raise as `SemanticScholarClientError`.
    """
    if not isinstance(paper_json, dict):
        raise TypeError(f"expected a paper object (dict), got {type(paper_json)!r}")

    semantic_scholar_id = paper_json.get("paperId")
    if not semantic_scholar_id:
        raise ValueError("Semantic Scholar paper is missing a 'paperId'")

    return SemanticScholarPaper(
        semantic_scholar_id=semantic_scholar_id,
        doi=_parse_doi(paper_json),
        title=paper_json.get("title") or "",
        citation_count=_parse_citation_count(paper_json, "citationCount"),
        influential_citation_count=_parse_citation_count(
            paper_json, "influentialCitationCount"
        ),
        embedding=_parse_embedding(paper_json),
        tldr=_parse_tldr(paper_json),
    )


def _handle_response(response: requests.Response, url: str) -> Any:
    """Validate an HTTP response and return its decoded JSON body.

    Raises `SemanticScholarClientError` for a non-2xx response or a body
    that isn't valid JSON — the caller still validates the JSON's shape
    (object vs. array) itself, since that differs between the single-GET
    and batch-POST endpoints.
    """
    if not response.ok:
        raise SemanticScholarClientError(
            f"Semantic Scholar returned HTTP {response.status_code} for {url}",
            status_code=response.status_code,
        )

    try:
        return response.json()
    except ValueError as exc:
        raise SemanticScholarClientError(
            f"Semantic Scholar returned a non-JSON response body: {exc}",
            status_code=response.status_code,
        ) from exc


def _get(url: str, params: dict[str, Any]) -> tuple[dict, int]:
    """GET `url`, returning the decoded JSON object body and status code.

    Raises `SemanticScholarClientError` for any network failure, non-2xx
    response, or a body that isn't a JSON object — never lets a raw
    `requests` exception escape.
    """
    try:
        response = requests.get(
            url, params=params, headers=_headers(), timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise SemanticScholarClientError(
            f"Network error calling Semantic Scholar: {exc}", status_code=None
        ) from exc

    data = _handle_response(response, url)

    if not isinstance(data, dict):
        raise SemanticScholarClientError(
            "Semantic Scholar returned an unexpected response body shape "
            "(not a JSON object)",
            status_code=response.status_code,
        )

    return data, response.status_code


def _post(url: str, params: dict[str, Any], json_body: dict) -> tuple[list, int]:
    """POST `url`, returning the decoded JSON array body and status code.

    Raises `SemanticScholarClientError` for any network failure, non-2xx
    response, or a body that isn't a JSON array — never lets a raw
    `requests` exception escape.
    """
    try:
        response = requests.post(
            url,
            params=params,
            json=json_body,
            headers=_headers(),
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SemanticScholarClientError(
            f"Network error calling Semantic Scholar: {exc}", status_code=None
        ) from exc

    data = _handle_response(response, url)

    if not isinstance(data, list):
        raise SemanticScholarClientError(
            "Semantic Scholar returned an unexpected response body shape "
            "(not a JSON array)",
            status_code=response.status_code,
        )

    return data, response.status_code


def get_paper(doi: str) -> SemanticScholarPaper:
    """Fetch one paper's embedding + citation-influence data by bare DOI.

    `doi` is the bare DOI (e.g. `10.1038/nature12373`, no `DOI:` prefix
    or URL) — this function adds the `DOI:` prefix internally when
    calling Semantic Scholar. Raises `SemanticScholarClientError`
    (`status_code=404`) for a DOI Semantic Scholar has no record for.
    """
    url = f"{_BASE_URL}/paper/DOI:{doi}"
    data, status_code = _get(url, params={"fields": _FIELDS})

    try:
        return _parse_paper(data)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SemanticScholarClientError(
            f"Could not parse Semantic Scholar paper response: {exc}",
            status_code=status_code,
        ) from exc


def get_papers(dois: list[str]) -> list[SemanticScholarPaper | None]:
    """Batch-fetch multiple papers by bare DOI in a single HTTP call.

    Returns a list positionally aligned to `dois` — same length, same
    order — with `None` at any index whose DOI Semantic Scholar has no
    record for (confirmed live: an unmatched ID comes back as a `null`
    entry in the response array, not an error and not an omitted
    element).
    """
    if not dois:
        return []

    url = f"{_BASE_URL}/paper/batch"
    ids = [f"DOI:{doi}" for doi in dois]
    data, status_code = _post(url, params={"fields": _FIELDS}, json_body={"ids": ids})

    if len(data) != len(dois):
        raise SemanticScholarClientError(
            "Semantic Scholar batch response length did not match the "
            f"number of requested DOIs (requested {len(dois)}, got {len(data)})",
            status_code=status_code,
        )

    results: list[SemanticScholarPaper | None] = []
    try:
        for paper_json in data:
            if paper_json is None:
                results.append(None)
            else:
                results.append(_parse_paper(paper_json))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SemanticScholarClientError(
            f"Could not parse a Semantic Scholar paper in batch results: {exc}",
            status_code=status_code,
        ) from exc

    return results
