"""A plain-Python client for the Semantic Scholar Graph API
(https://api.semanticscholar.org).

Per GitHub issue #20: this package has zero Django coupling — no
`django.*` import, no `papers.models` import, no database access — so it
can be used by any synchronous caller (#21: store embeddings; #22:
influential-citation ratio in scoring) and unit-tested without a
database.

Public API:

    from semantic_scholar_client import (
        get_paper,
        get_papers,
        SemanticScholarPaper,
        SemanticScholarClientError,
    )
"""

from .client import get_paper, get_papers
from .exceptions import SemanticScholarClientError
from .types import SemanticScholarPaper

__all__ = [
    "SemanticScholarClientError",
    "SemanticScholarPaper",
    "get_paper",
    "get_papers",
]
