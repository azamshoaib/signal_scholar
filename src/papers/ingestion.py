"""Shared write-side ingestion/dedupe logic for `OpenAlexWork`s.

Per GitHub issue #26: this is the upsert/dedupe logic that used to live as
free functions / `Command` methods inside `ingest_openalex.py` (issues
#9/#10), extracted here so more than one caller can go through the exact
same code path instead of a parallel one — today `ingest_openalex` (a
topic search) and `poll_followed_authors` (per-author polling, #26) both
call `ingest_works` below.

This module is deliberately distinct from `papers/services.py`, which is
documented as this app's *read*-side query logic (`search_papers`);
ingestion is write-side upsert logic and is kept separate.

Dedupe/matching is by `openalex_id` via `get_or_create`, which is a real DB
query — so it naturally matches rows written by a *previous* invocation of
an ingesting command, not just a shared co-author/journal/institution seen
twice within the same batch. `Author.openalex_id`/`Institution.openalex_id`/
`Venue.openalex_id` are all `unique=True`, so a match updates `name` in
place (see `_get_or_create_by_openalex_id`); `Author.institution` is only
ever set when the `Author` row is newly created (first occurrence wins,
issue #9), and reconciling it on a later match is explicitly deferred to
#30.

`Paper` is matched the same way, by `openalex_id` (issue #10) — see
`_match_or_create_paper` for the field-update rules on a match, including
`doi`'s special conflict handling (a differing incoming `doi` is never
allowed to overwrite a stored one, since that's exactly what produced the
`IntegrityError` #10 exists to fix). Matched `Paper` rows have their
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

from dataclasses import dataclass
from typing import Callable

from django.db.models import Model

from openalex_client import (
    OpenAlexAuthor,
    OpenAlexInstitution,
    OpenAlexVenue,
    OpenAlexWork,
)
from papers.models import Author, Institution, Paper, PaperAuthorship, Venue


@dataclass
class IngestionCounts:
    """Counters for one `ingest_works` call.

    The exact set of counters `ingest_openalex.py` already printed before
    this extraction (issue #26).
    """

    papers_created: int = 0
    papers_updated: int = 0
    authors_created: int = 0
    institutions_created: int = 0
    venues_created: int = 0


def _get_or_create_by_openalex_id(
    model: type[Model],
    external_id: str | None,
    name: str,
) -> tuple[Model, bool]:
    """Get-or-create a `model` row keyed on `openalex_id`.

    This is a real DB query, so it matches rows from a previous ingestion
    run too, not just within the current one.

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


def _resolve_doi(
    openalex_id: str | None,
    stored_doi: str | None,
    incoming_doi: str | None,
    on_warning: Callable[[str], None],
) -> str | None:
    """Resolve the `doi` to store on a matched `Paper` (issue #10).

    - stored `None`, incoming not `None` -> fill it in.
    - stored equals incoming (including both `None`) -> no-op.
    - stored not `None`, incoming `None` -> keep stored (a re-fetch
      with missing data must never erase a doi we already have).
    - stored not `None`, incoming not `None`, and they differ -> keep
      stored, and report a warning via `on_warning` (overwriting risks the
      exact `IntegrityError` this rule exists to fix, via a collision with
      a *different* existing `Paper` row).
    """
    if stored_doi == incoming_doi:
        return stored_doi
    if stored_doi is None:
        return incoming_doi
    if incoming_doi is None:
        return stored_doi
    on_warning(
        f"Warning: Paper with openalex_id={openalex_id!r} has stored "
        f"doi={stored_doi!r}, which differs from incoming "
        f"doi={incoming_doi!r}. Keeping the stored doi."
    )
    return stored_doi


def _match_or_create_paper(
    work: OpenAlexWork,
    venue: Venue | None,
    on_warning: Callable[[str], None],
) -> tuple[Paper, bool]:
    """Match an existing `Paper` by `openalex_id`, or create a new one.

    Mirrors `_get_or_create_by_openalex_id`'s "never match on a `None`
    key" rule: a work with `openalex_id=None` always creates a fresh
    `Paper` row (issue #10) — `filter(openalex_id=None)` would wrongly
    match unrelated rows, since Postgres allows multiple `NULL`s under
    the unique constraint.

    On a match, `title`/`publication_year`/`abstract`/`venue`/
    `cited_by_count`/`counts_by_year` are overwritten unconditionally
    with the incoming value — citation counts go stale and should
    refresh on every re-ingestion (issue #34), same as the other
    unconditionally-overwritten fields, no `doi`-style conflict
    handling needed; `doi` is resolved via `_resolve_doi` (see its
    docstring for the conflict rule); `openalex_id` itself is never
    changed on a matched row.
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
            cited_by_count=work.cited_by_count,
            counts_by_year=work.counts_by_year,
        )
        return paper, True

    existing.title = work.title
    existing.publication_year = work.publication_year
    existing.abstract = work.abstract
    existing.venue = venue
    existing.doi = _resolve_doi(existing.openalex_id, existing.doi, work.doi, on_warning)
    existing.cited_by_count = work.cited_by_count
    existing.counts_by_year = work.counts_by_year
    existing.save()
    return existing, False


def _get_or_create_venue(openalex_venue: OpenAlexVenue) -> tuple[Venue, bool]:
    return _get_or_create_by_openalex_id(Venue, openalex_venue.openalex_id, openalex_venue.name)


def _get_or_create_institution(
    openalex_institution: OpenAlexInstitution,
) -> tuple[Institution, bool]:
    return _get_or_create_by_openalex_id(
        Institution, openalex_institution.openalex_id, openalex_institution.name
    )


def _get_or_create_author(openalex_author: OpenAlexAuthor) -> tuple[Author, bool]:
    return _get_or_create_by_openalex_id(Author, openalex_author.openalex_id, openalex_author.name)


def ingest_works(
    works: list[OpenAlexWork],
    on_warning: Callable[[str], None] | None = None,
) -> IngestionCounts:
    """Upsert `works` into the local DB, returning row-count deltas.

    The single reusable entry point both `ingest_openalex` and
    `poll_followed_authors` call (issue #26) — "via the existing
    ingestion/dedupe logic (#9-10), not a parallel code path", satisfied
    literally: both commands call this exact function.

    `on_warning`, when given, is called with human-readable warning text
    (currently only the `doi`-conflict warning from `_resolve_doi`) so a
    caller can surface it however it likes (e.g. a management command's
    `self.stdout.write`). Defaults to a no-op.
    """
    if on_warning is None:
        on_warning = lambda _message: None  # noqa: E731

    counts = IngestionCounts()

    for work in works:
        venue = None
        if work.venue is not None:
            venue, venue_created = _get_or_create_venue(work.venue)
            if venue_created:
                counts.venues_created += 1

        paper, paper_created = _match_or_create_paper(work, venue, on_warning)
        if paper_created:
            counts.papers_created += 1
        else:
            counts.papers_updated += 1
            # Matched row: reconcile authorship by deleting existing rows
            # and recreating fresh ones below, rather than diffing the old
            # and new author lists in place (issue #10) — a diff can
            # transiently collide with PaperAuthorship's unique_together
            # constraints when the author list changes shape (e.g. two
            # authors swapping position).
            PaperAuthorship.objects.filter(paper=paper).delete()

        for position, openalex_author in enumerate(work.authors, start=1):
            author, author_created = _get_or_create_author(openalex_author)

            if author_created:
                counts.authors_created += 1
                # Only a newly-created Author row gets its institution set
                # here — a row matched from earlier in this same run keeps
                # whatever institution its first occurrence gave it (issue
                # #9: first occurrence in the run wins).
                if openalex_author.institutions:
                    institution, institution_created = _get_or_create_institution(
                        openalex_author.institutions[0]
                    )
                    if institution_created:
                        counts.institutions_created += 1
                    author.institution = institution
                    author.save(update_fields=["institution"])

            PaperAuthorship.objects.create(paper=paper, author=author, position=position)

    return counts
