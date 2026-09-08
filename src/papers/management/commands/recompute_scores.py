"""Management command: (re)compute every stored score field.

Per GitHub issue #14: `uv run python manage.py recompute_scores` recomputes
and re-stores `Author.h_index`/`h_index_normalized` (#11),
`Paper.citation_velocity` (#12), and
`Paper.author_reputation_score`/`velocity_score`/`combined_score` (#13) for
every `Author`/`Paper` already in the database. This decouples scoring from
request-time/ingest-time computation and is the seam #28 later hooks a
schedule into.

This command deliberately does no scoring math itself -- it only calls the
existing `update_author_h_index`, `update_paper_citation_velocity`, and
`update_paper_combined_score` functions from `papers.scoring` (already
unit-tested by #11-#13) in the right order.

Operation order is a hard, three-phase constraint, not a suggestion:

1. Recompute + save `h_index`/`h_index_normalized` for every `Author`, and
   let that fully finish (and, via Postgres autocommit, commit) before
   phase 2 starts.
2. Recompute `citation_velocity` for every `Paper`.
3. Recompute `author_reputation_score`/`velocity_score`/`combined_score`
   for every `Paper`.

Phases 2 and 3 are merged into a single pass over papers here (compute
velocity, then combined score off the in-memory-updated paper, then one
`.save()` per paper) -- that's fine per the issue, since neither depends on
when *paper* fields were computed relative to each other, only that phase 1
(author) is fully done first.

The `Paper` queryset driving phases 2/3 is built *after* phase 1's loop has
finished, not reused from anything fetched earlier -- `update_paper_combined_score`
-> `compute_paper_author_reputation_score` reads `first_authorship.author.h_index_normalized`
as already stored on the `Author` row; it does not recompute it. Building
(and prefetching) the `Paper` queryset before phase 1 runs -- or reusing a
queryset/prefetch cache populated before phase 1's author saves landed --
would silently compute `combined_score` from stale `h_index_normalized`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from papers.models import Author, Paper
from papers.scoring import (
    update_author_h_index,
    update_paper_citation_velocity,
    update_paper_combined_score,
)


class Command(BaseCommand):
    help = (
        "Recompute and store Author.h_index/h_index_normalized, "
        "Paper.citation_velocity, and Paper.author_reputation_score/"
        "velocity_score/combined_score for every Author/Paper in the database."
    )

    def handle(self, *args, **options) -> None:
        # Phase 1: every Author, fully finished before phase 2/3 start.
        # `prefetch_related("papers")` avoids one query per author from
        # `compute_author_h_index_scores`'s `author.papers.all()`.
        authors_recomputed = 0
        for author in Author.objects.prefetch_related("papers"):
            update_author_h_index(author)
            authors_recomputed += 1

        # Phases 2+3, merged: the Paper queryset is (re-)fetched here, after
        # phase 1 has fully completed, so `update_paper_combined_score`
        # reads each paper's first author's freshly-saved
        # `h_index_normalized`, not a stale value. `prefetch_related`
        # avoids one query per paper from
        # `compute_paper_author_reputation_score`'s
        # `paper.authorships.order_by("position").first()`.
        papers_recomputed = 0
        for paper in Paper.objects.prefetch_related("authorships__author"):
            update_paper_citation_velocity(paper, save=False)
            update_paper_combined_score(paper, save=False)
            paper.save(
                update_fields=[
                    "citation_velocity",
                    "author_reputation_score",
                    "velocity_score",
                    "combined_score",
                ]
            )
            papers_recomputed += 1

        self.stdout.write(f"Authors recomputed: {authors_recomputed}")
        self.stdout.write(f"Papers recomputed: {papers_recomputed}")
