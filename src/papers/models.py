"""Core domain models for the SignalScholar schema.

See GitHub issue #5. `Paper`, `Author`, `Institution`, and the ordered
`PaperAuthorship` through-model are the base relational schema that later
ingestion (#8, #9), admin (#7), and scoring (#11-13, #22) tasks build on.
`Venue` and `Citation` are added to this same app by #6.

External IDs (`openalex_id` on `Paper`, `Author`, `Institution`) store
OpenAlex's short form (e.g. ``W2741809807``), not the full URL. They are
``unique=True`` and ``null=True`` — Postgres allows multiple NULLs under a
unique constraint, so not-yet-matched rows are fine, and ``unique=True``
already creates the index we'd otherwise add via ``db_index``.
"""

from django.db import models


class Institution(models.Model):
    """An academic institution, as identified by OpenAlex."""

    name = models.CharField(max_length=500)
    openalex_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    def __str__(self) -> str:
        return self.name


class Author(models.Model):
    """A paper author.

    `institution` is a single nullable FK representing the author's
    current/primary affiliation only — not a historical or
    multi-institution affiliation record (see issue #5's Constraints;
    that gap is deliberately deferred to #30).
    """

    name = models.CharField(max_length=500)
    openalex_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    institution = models.ForeignKey(
        Institution,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authors",
    )

    def __str__(self) -> str:
        return self.name


class Paper(models.Model):
    """A paper/publication."""

    title = models.TextField()
    publication_year = models.PositiveIntegerField(null=True, blank=True)
    doi = models.CharField(max_length=255, null=True, blank=True, unique=True)
    abstract = models.TextField(null=True, blank=True)
    openalex_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    authors = models.ManyToManyField(
        Author,
        through="PaperAuthorship",
        related_name="papers",
    )

    def __str__(self) -> str:
        return f"{self.title} ({self.publication_year})"


class PaperAuthorship(models.Model):
    """The ordered link between a `Paper` and one of its `Author`s.

    An explicit through-model rather than a bare `ManyToManyField` because
    author order is not cosmetic: first/last authorship is how academic
    credit is read, and the product's premise is reputation-aware ranking
    (see issue #5's Constraints).
    """

    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name="authorships")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="authorships")
    position = models.PositiveIntegerField()

    class Meta:
        unique_together = (
            ("paper", "author"),
            ("paper", "position"),
        )
        ordering = ["position"]

    def __str__(self) -> str:
        return f"{self.paper.title} - {self.author.name} (position {self.position})"
