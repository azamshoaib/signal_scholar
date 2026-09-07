"""The single exception type this client raises.

Per GitHub issue #8's Constraints: one flat `OpenAlexClientError`, no
subclass hierarchy yet. Callers that need to distinguish rate-limit vs.
not-found vs. generic errors will get that in #32, once a caller actually
branches on error type (neither #9 nor #10 do today).
"""

from __future__ import annotations


class OpenAlexClientError(Exception):
    """Raised for any network failure, non-2xx response, or malformed body.

    `status_code` is the HTTP status code when one was received (e.g. a
    404 or 500 from OpenAlex), and `None` when the failure happened before
    a response existed at all (a network error, timeout, or connection
    failure).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
