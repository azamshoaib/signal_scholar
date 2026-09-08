"""Management command: fetch and store Semantic Scholar embeddings for papers.

Per GitHub issue #21: `uv run python manage.py
fetch_semantic_scholar_embeddings` fetches each `doi`-having `Paper`'s
SPECTER v2 embedding from Semantic Scholar via
`semantic_scholar_client.get_papers` (the batch function -- never
`get_paper` in a loop, since #20 confirmed Semantic Scholar's
unauthenticated rate limit is tight and shared/global, not per-item) and
stores it on `Paper.embedding` (`pgvector.django.VectorField(dimensions=768)`,
added directly to `Paper` by this same issue).

Per GitHub issue #22, each matched paper's `Paper.influential_citation_ratio`
is also computed (`compute_influential_citation_ratio`, from
`result.influential_citation_count`/`result.citation_count`) and saved
alongside `embedding`. Neither raw Semantic Scholar count is itself stored
as a `Paper` column -- only the derived ratio (see issue #22's Constraints).

Batching: doi-having papers are chunked into groups of at most 500 --
Semantic Scholar's documented hard cap on `POST /paper/batch` -- and each
chunk's results are saved to the database before the next chunk is
requested, so a later chunk's failure does not lose an earlier chunk's
progress (`get_papers` is confirmed all-or-nothing per HTTP call, so there
is nothing to salvage from *within* a failed chunk -- only chunking +
saving between chunks protects earlier progress).

A DOI Semantic Scholar has no record for comes back as a positional `None`
in `get_papers`' response (per #20). That paper's `embedding` and
`influential_citation_ratio` are both left untouched (whatever they
already held -- `NULL`/`0.0` defaults on a first run, or a stale prior
value on a re-run) and counted separately from both "matched" and
"skipped (no DOI)".

`Paper` rows with `doi=None` have no join key (#20's Constraints: DOI is
the only realistic match key) and are never sent to Semantic Scholar --
skipped entirely, counted separately, `embedding` left untouched.

Re-running this command reprocesses and unconditionally overwrites the
`embedding` of every doi-having `Paper` -- not only ones with
`embedding IS NULL` -- per issue #21's acceptance criteria; no "only
missing" optimization.

On a `SemanticScholarClientError` from any chunk (e.g. an unretried 429 --
#38's retry/backoff is explicitly out of scope here), the command stops
processing further chunks and raises `CommandError`, reporting exactly how
many chunks/papers were already saved before the failure -- it must never
report overall success when only some chunks completed. No retry loop
belongs in this command; a rate-limited batch call fails the whole run
loudly, per issue #21's Constraints.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from papers.models import Paper
from papers.scoring import compute_influential_citation_ratio
from semantic_scholar_client import SemanticScholarClientError, get_papers

# Semantic Scholar's documented hard cap on `POST /paper/batch`: a 501-ID
# request returns HTTP 400 ("Maximum 500 ids allowed in input list"). Not a
# rate-limiting safety margin and not configurable -- see issue #21's
# Constraints.
_CHUNK_SIZE = 500


def _chunked(items: list[Paper], size: int) -> list[list[Paper]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


class Command(BaseCommand):
    help = (
        "Fetch and store Semantic Scholar SPECTER v2 embeddings for every "
        "Paper with a non-null doi, via semantic_scholar_client.get_papers "
        "(batched, at most 500 DOIs per call)."
    )

    def handle(self, *args, **options) -> None:
        papers_skipped_no_doi = Paper.objects.filter(doi__isnull=True).count()

        # Ordered so chunking is deterministic (helpful for tests and for
        # reasoning about "how far did we get" on a mid-run failure).
        papers_with_doi = list(Paper.objects.filter(doi__isnull=False).order_by("pk"))
        chunks = _chunked(papers_with_doi, _CHUNK_SIZE)

        papers_matched = 0
        papers_not_found = 0
        chunks_succeeded = 0

        for chunk in chunks:
            dois = [paper.doi for paper in chunk]
            try:
                results = get_papers(dois)
            except SemanticScholarClientError as exc:
                raise CommandError(
                    "Semantic Scholar batch call failed on chunk "
                    f"{chunks_succeeded + 1} of {len(chunks)} "
                    f"({chunks_succeeded} chunk(s) / {papers_matched} paper(s) "
                    f"already updated before the failure): {exc}"
                ) from exc

            # Save this chunk's results before requesting the next chunk,
            # so a later chunk's failure does not lose this progress.
            for paper, result in zip(chunk, results):
                if result is None:
                    # No Semantic Scholar record for this DOI: leave
                    # `embedding` untouched, do not write anything.
                    papers_not_found += 1
                    continue
                paper.embedding = result.embedding
                paper.influential_citation_ratio = compute_influential_citation_ratio(
                    result.influential_citation_count, result.citation_count
                )
                paper.save(update_fields=["embedding", "influential_citation_ratio"])
                papers_matched += 1

            chunks_succeeded += 1

        self.stdout.write(f"Papers processed: {len(papers_with_doi)}")
        self.stdout.write(f"Papers matched: {papers_matched}")
        self.stdout.write(f"Papers skipped (no DOI): {papers_skipped_no_doi}")
        self.stdout.write(f"No Semantic Scholar match: {papers_not_found}")
