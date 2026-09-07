"""Management command: ingest an OpenAlex topic search into the local DB.

Per GitHub issue #9: `uv run python manage.py ingest_openalex "<topic>"` calls
`openalex_client.search_works` and, for each `OpenAlexWork` returned, writes a
`Paper` row plus `Author`/`Institution`/`Venue` rows and an ordered
`PaperAuthorship` row per author.

Dedupe here is *within this run only* — an `openalex_id` seen twice in the
same batch (a shared co-author, journal, or institution across two fetched
papers) resolves to a single DB row via `get_or_create`, since
`Author.openalex_id`/`Institution.openalex_id`/`Venue.openalex_id` are all
`unique=True`. Matching against rows written by a *previous* invocation of
this command is explicitly out of scope (#10) — running this command twice
against the same topic is expected to create duplicate rows across the two
runs.

A row with `openalex_id=None` is never matched by name; it is always
created fresh (issue #9's Constraints / #8's `OpenAlexAuthor`/`OpenAlexVenue`/
`OpenAlexInstitution` docstrings).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Model

from openalex_client import (
    OpenAlexAuthor,
    OpenAlexInstitution,
    OpenAlexVenue,
    search_works,
)
from papers.models import Author, Institution, Paper, PaperAuthorship, Venue


def _get_or_create_by_openalex_id(
    model: type[Model],
    external_id: str | None,
    name: str,
) -> tuple[Model, bool]:
    """Get-or-create a `model` row keyed on `openalex_id`, within this run.

    When `external_id` is `None`, there is no safe key to match on (per
    issue #9: never match by name), so a fresh row is always created —
    `created` is unconditionally `True` in that branch.
    """
    if external_id is not None:
        return model.objects.get_or_create(
            openalex_id=external_id,
            defaults={"name": name},
        )
    return model.objects.create(name=name), True


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

        papers_created = 0
        authors_created = 0
        institutions_created = 0
        venues_created = 0

        for work in works:
            venue = None
            if work.venue is not None:
                venue, venue_created = self._get_or_create_venue(work.venue)
                if venue_created:
                    venues_created += 1

            paper = Paper.objects.create(
                title=work.title,
                publication_year=work.publication_year,
                doi=work.doi,
                abstract=work.abstract,
                openalex_id=work.openalex_id,
                venue=venue,
            )
            papers_created += 1

            for position, openalex_author in enumerate(work.authors, start=1):
                author, author_created = self._get_or_create_author(openalex_author)

                if author_created:
                    authors_created += 1
                    # Only a newly-created Author row gets its institution
                    # set here — a row matched from earlier in this same
                    # run keeps whatever institution its first occurrence
                    # gave it (issue #9: first occurrence in the run wins).
                    if openalex_author.institutions:
                        institution, institution_created = self._get_or_create_institution(
                            openalex_author.institutions[0]
                        )
                        if institution_created:
                            institutions_created += 1
                        author.institution = institution
                        author.save(update_fields=["institution"])

                PaperAuthorship.objects.create(paper=paper, author=author, position=position)

        self.stdout.write(f"Papers created: {papers_created}")
        self.stdout.write(f"Authors created: {authors_created}")
        self.stdout.write(f"Institutions created: {institutions_created}")
        self.stdout.write(f"Venues created: {venues_created}")

    @staticmethod
    def _get_or_create_venue(openalex_venue: OpenAlexVenue) -> tuple[Venue, bool]:
        return _get_or_create_by_openalex_id(Venue, openalex_venue.openalex_id, openalex_venue.name)

    @staticmethod
    def _get_or_create_institution(
        openalex_institution: OpenAlexInstitution,
    ) -> tuple[Institution, bool]:
        return _get_or_create_by_openalex_id(
            Institution, openalex_institution.openalex_id, openalex_institution.name
        )

    @staticmethod
    def _get_or_create_author(openalex_author: OpenAlexAuthor) -> tuple[Author, bool]:
        return _get_or_create_by_openalex_id(Author, openalex_author.openalex_id, openalex_author.name)
