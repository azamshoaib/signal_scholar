"""Management command: ingest an OpenAlex topic search into the local DB.

Per GitHub issue #9: `uv run python manage.py ingest_openalex "<topic>"` calls
`openalex_client.search_works` and, for each `OpenAlexWork` returned, writes a
`Paper` row plus `Author`/`Institution`/`Venue` rows and an ordered
`PaperAuthorship` row per author.

Dedupe/matching is by `openalex_id` via `get_or_create`, which is a real DB
query — so it naturally matches rows written by a *previous* invocation of
this command, not just a shared co-author/journal/institution seen twice
within the same batch. `Author.openalex_id`/`Institution.openalex_id`/
`Venue.openalex_id` are all `unique=True`, so a match updates `name` in
place (see `_get_or_create_by_openalex_id`); `Author.institution` is only
ever set when the `Author` row is newly created (first occurrence wins,
issue #9), and reconciling it on a later match is explicitly deferred to
#30.

`Paper` is matched the same way, by `openalex_id` (issue #10) — see
`Command._match_or_create_paper` for the field-update rules on a match,
including `doi`'s special conflict handling (a differing incoming `doi` is
never allowed to overwrite a stored one, since that's exactly what produced
the `IntegrityError` #10 exists to fix). Matched `Paper` rows have their
`PaperAuthorship` rows deleted and recreated fresh from the current run's
author list, rather than diffed in place.

A row with `openalex_id=None` is never matched by name; it is always
created fresh (issue #9's Constraints / #8's `OpenAlexAuthor`/`OpenAlexVenue`/
`OpenAlexInstitution` docstrings) — this applies to `Paper` too (#10): a
work with `openalex_id=None` always creates a new `Paper` row, never
matching another row (including another `openalex_id=None` row), since
Postgres allows multiple `NULL`s under a unique constraint.
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
    """Get-or-create a `model` row keyed on `openalex_id`.

    This is a real DB query, so it matches rows from a previous invocation
    of this command too, not just within the current run.

    When `external_id` is `None`, there is no safe key to match on (per
    issue #9: never match by name), so a fresh row is always created —
    `created` is unconditionally `True` in that branch.

    On a match (`created` is `False`), `name` is overwritten with the
    incoming value (issue #10) — `Author`/`Institution`/`Venue` all just
    have `name` as their one non-key, non-relation field to keep in sync.
    """
    if external_id is not None:
        obj, created = model.objects.get_or_create(
            openalex_id=external_id,
            defaults={"name": name},
        )
        if not created and obj.name != name:
            obj.name = name
            obj.save(update_fields=["name"])
        return obj, created
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
        papers_updated = 0
        authors_created = 0
        institutions_created = 0
        venues_created = 0

        for work in works:
            venue = None
            if work.venue is not None:
                venue, venue_created = self._get_or_create_venue(work.venue)
                if venue_created:
                    venues_created += 1

            paper, paper_created = self._match_or_create_paper(work, venue)
            if paper_created:
                papers_created += 1
            else:
                papers_updated += 1
                # Matched row: reconcile authorship by deleting existing
                # rows and recreating fresh ones below, rather than diffing
                # the old and new author lists in place (issue #10) — a
                # diff can transiently collide with PaperAuthorship's
                # unique_together constraints when the author list changes
                # shape (e.g. two authors swapping position).
                PaperAuthorship.objects.filter(paper=paper).delete()

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
        self.stdout.write(f"Papers updated: {papers_updated}")
        self.stdout.write(f"Authors created: {authors_created}")
        self.stdout.write(f"Institutions created: {institutions_created}")
        self.stdout.write(f"Venues created: {venues_created}")

    def _match_or_create_paper(self, work, venue: Venue | None) -> tuple[Paper, bool]:
        """Match an existing `Paper` by `openalex_id`, or create a new one.

        Mirrors `_get_or_create_by_openalex_id`'s "never match on a `None`
        key" rule: a work with `openalex_id=None` always creates a fresh
        `Paper` row (issue #10) — `filter(openalex_id=None)` would wrongly
        match unrelated rows, since Postgres allows multiple `NULL`s under
        the unique constraint.

        On a match, `title`/`publication_year`/`abstract`/`venue` are
        overwritten unconditionally with the incoming value; `doi` is
        resolved via `_resolve_doi` (see its docstring for the conflict
        rule); `openalex_id` itself is never changed on a matched row.
        """
        existing = None
        if work.openalex_id is not None:
            existing = Paper.objects.filter(openalex_id=work.openalex_id).first()

        if existing is None:
            paper = Paper.objects.create(
                title=work.title,
                publication_year=work.publication_year,
                doi=work.doi,
                abstract=work.abstract,
                openalex_id=work.openalex_id,
                venue=venue,
            )
            return paper, True

        existing.title = work.title
        existing.publication_year = work.publication_year
        existing.abstract = work.abstract
        existing.venue = venue
        existing.doi = self._resolve_doi(existing.openalex_id, existing.doi, work.doi)
        existing.save()
        return existing, False

    def _resolve_doi(
        self,
        openalex_id: str | None,
        stored_doi: str | None,
        incoming_doi: str | None,
    ) -> str | None:
        """Resolve the `doi` to store on a matched `Paper` (issue #10).

        - stored `None`, incoming not `None` -> fill it in.
        - stored equals incoming (including both `None`) -> no-op.
        - stored not `None`, incoming `None` -> keep stored (a re-fetch
          with missing data must never erase a doi we already have).
        - stored not `None`, incoming not `None`, and they differ -> keep
          stored, and print a warning (overwriting risks the exact
          `IntegrityError` this task exists to fix, via a collision with a
          *different* existing `Paper` row).
        """
        if stored_doi == incoming_doi:
            return stored_doi
        if stored_doi is None:
            return incoming_doi
        if incoming_doi is None:
            return stored_doi
        self.stdout.write(
            f"Warning: Paper with openalex_id={openalex_id!r} has stored "
            f"doi={stored_doi!r}, which differs from incoming "
            f"doi={incoming_doi!r}. Keeping the stored doi."
        )
        return stored_doi

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
