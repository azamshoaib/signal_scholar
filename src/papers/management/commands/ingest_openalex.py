"""Management command: ingest an OpenAlex topic search into the local DB.

Per GitHub issue #9: `uv run python manage.py ingest_openalex "<topic>"` calls
`openalex_client.search_works` and, for each `OpenAlexWork` returned, writes a
`Paper` row plus `Author`/`Institution`/`Venue` rows and an ordered
`PaperAuthorship` row per author.

Per GitHub issue #26, the actual upsert/dedupe logic (matching by
`openalex_id`, the `doi`-conflict rule, authorship reconciliation, etc.)
has been extracted into `papers.ingestion.ingest_works` so both this
command and `poll_followed_authors` call the exact same code path — see
that module's docstring for the dedupe/matching rules themselves
(unchanged by this refactor, just relocated). This command's own
CLI/output format is unchanged.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from openalex_client import search_works
from papers.ingestion import ingest_works


class Command(BaseCommand):
    help = "Ingest papers from an OpenAlex topic search into the local database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("topic", type=str, help="Topic/keyword string to search OpenAlex for.")
        parser.add_argument(
            "--max-results",
            type=int,
            default=25,
            help="Maximum number of works to fetch from OpenAlex (default: 25).",
        )

    def handle(self, *args, **options) -> None:
        topic: str = options["topic"]
        max_results: int = options["max_results"]

        works = search_works(topic, max_results=max_results)
        counts = ingest_works(works, on_warning=self.stdout.write)

        self.stdout.write(f"Papers created: {counts.papers_created}")
        self.stdout.write(f"Papers updated: {counts.papers_updated}")
        self.stdout.write(f"Authors created: {counts.authors_created}")
        self.stdout.write(f"Institutions created: {counts.institutions_created}")
        self.stdout.write(f"Venues created: {counts.venues_created}")
