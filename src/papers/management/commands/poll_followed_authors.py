"""Management command: poll followed authors for new OpenAlex works.

Per GitHub issue #26: `uv run python manage.py poll_followed_authors` finds
every distinct `Author` followed by any user (via `Follow.author`) and, for
each one that has an `openalex_id`, fetches that author's most recent
OpenAlex works and runs them through the exact same ingest/dedupe path
`ingest_openalex` uses (`papers.ingestion.ingest_works`) — not a parallel
code path, per the issue's explicit requirement.

No "last polled" timestamp or any other new persisted state is added: every
run re-fetches each followed author's `N` most recent works and relies
entirely on `ingest_works`'s existing `openalex_id`-based dedupe (#9/#10) to
tell new papers from already-known ones. See issue #26's Constraints for why
this is the deliberate design choice over tracking a date cursor (a
followed author who publishes more than `N` works between two runs can have
the oldest of that overflow missed until `N` is raised or the command runs
more often — a known, accepted limitation for this MVP).

`Follow` rows where `institution` is set (not `author`) are never queried by
this command — polling followed institutions is out of scope for #26
(tracked separately as #43).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from openalex_client import search_works_by_author
from papers.ingestion import ingest_works
from papers.models import Author, Follow


class Command(BaseCommand):
    help = "Poll OpenAlex for new works by every distinct followed Author."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--max-results-per-author",
            type=int,
            default=25,
            help="Maximum number of works to fetch per author from OpenAlex (default: 25).",
        )

    def handle(self, *args, **options) -> None:
        max_results_per_author: int = options["max_results_per_author"]

        # Distinct set of followed authors across all users, in one query —
        # an author followed by 5 users is queried against OpenAlex once
        # per run, not five times (issue #26).
        followed_author_ids = (
            Follow.objects.filter(author__isnull=False)
            .values_list("author", flat=True)
            .distinct()
        )
        followed_authors = list(Author.objects.filter(pk__in=followed_author_ids))

        authors_skipped = 0
        authors_polled = 0
        papers_created = 0
        papers_updated = 0
        authors_zero_new = 0

        for author in followed_authors:
            if not author.openalex_id:
                # No safe external ID to query OpenAlex with — skipped and
                # counted separately, mirroring #21's "no DOI -> skip,
                # count separately" precedent.
                authors_skipped += 1
                continue

            authors_polled += 1
            works = search_works_by_author(
                author.openalex_id, max_results=max_results_per_author
            )
            counts = ingest_works(works, on_warning=self.stdout.write)

            papers_created += counts.papers_created
            papers_updated += counts.papers_updated
            if counts.papers_created == 0:
                # Covers both "all fetched works already known" and "author
                # has zero works on OpenAlex" — both yield papers_created == 0.
                authors_zero_new += 1

        self.stdout.write(f"Followed authors (distinct): {len(followed_authors)}")
        self.stdout.write(f"Authors skipped (no openalex_id): {authors_skipped}")
        self.stdout.write(f"Authors polled: {authors_polled}")
        self.stdout.write(f"Papers created: {papers_created}")
        self.stdout.write(f"Papers updated: {papers_updated}")
        self.stdout.write(f"Authors with zero new papers this run: {authors_zero_new}")
