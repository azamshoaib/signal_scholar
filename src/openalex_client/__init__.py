"""A plain-Python client for the OpenAlex API (https://openalex.org).

Per GitHub issue #8: this package has zero Django coupling — no
`django.*` import, no `papers.models` import, no database access — so it
can be used by any synchronous caller (today: #9's ingestion command;
later: #26's polling job) and unit-tested without a database.

Public API:

    from openalex_client import (
        search_works,
        search_works_by_author,
        get_work,
        OpenAlexWork,
        OpenAlexAuthor,
        OpenAlexVenue,
        OpenAlexInstitution,
        OpenAlexClientError,
    )
"""

from .client import get_work, search_works, search_works_by_author
from .exceptions import OpenAlexClientError
from .types import OpenAlexAuthor, OpenAlexInstitution, OpenAlexVenue, OpenAlexWork

__all__ = [
    "OpenAlexAuthor",
    "OpenAlexClientError",
    "OpenAlexInstitution",
    "OpenAlexVenue",
    "OpenAlexWork",
    "get_work",
    "search_works",
    "search_works_by_author",
]
