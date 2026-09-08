"""The single plain dataclass returned by this client.

Per GitHub issue #20, these are the fields #21 (store embeddings) and #22
(influential-citation ratio in scoring) consume directly — no Django
import here, no coupling to `papers.models`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SemanticScholarPaper:
    # Semantic Scholar's own `paperId` (e.g.
    # `a5de30adc5c22bc86e8cfabe7fbd07c052d196a8`). Kept for
    # logging/debugging only, **not** a join key — Semantic Scholar's
    # `paperId` has no relationship to OpenAlex's `W...` IDs already
    # stored as `Paper.openalex_id` (#5); #21 must join back onto local
    # `Paper` rows via `doi` below, per issue #20's Constraints.
    semantic_scholar_id: str
    # The bare DOI from the response's `externalIds.DOI`; `None` on the
    # rare response that has no DOI on file. Every paper this client is
    # called for was looked up *by* DOI, so this should normally echo the
    # input, but it is parsed from the response rather than assumed.
    doi: str | None
    title: str = ""
    # Per issue #20 (mirroring #34's `_parse_cited_by_count` exactly,
    # including excluding `bool`, a subclass of `int` in Python): defaults
    # to `0` if missing or not an int.
    citation_count: int = 0
    influential_citation_count: int = 0
    # 768-dim SPECTER v2 vector (`fields=embedding.specter_v2`), or `None`
    # if Semantic Scholar has no embedding for this paper, or if the field
    # is present but malformed.
    embedding: list[float] | None = None
    # Just the summary text (`tldr.text`); `None` if `tldr` is
    # absent/`null` or malformed. Semantic Scholar's `tldr` object also
    # carries a `model` field (e.g. `tldr@v2.0.0`); this client discards
    # it, matching #8's pattern of returning only the fields downstream
    # code actually needs.
    tldr: str | None = None
