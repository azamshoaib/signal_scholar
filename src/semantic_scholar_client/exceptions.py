"""The single exception type this client raises.

Per GitHub issue #20's Constraints, mirroring #8/`OpenAlexClientError`'s
design exactly: one flat `SemanticScholarClientError`, no subclass
hierarchy. Distinguishing rate-limit (HTTP 429) vs. not-found vs. generic
errors is deferred to #38, once a caller (#21/#22) actually needs to
branch on error type.
"""

from __future__ import annotations


class SemanticScholarClientError(Exception):
    """Raised for any network failure, non-2xx response, or malformed body.

    `status_code` is the HTTP status code when one was received (e.g. a
    404 from a DOI Semantic Scholar has no record for, or a 429 from its
    rate limiter), and `None` when the failure happened before a response
    existed at all (a network error, timeout, or connection failure).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
