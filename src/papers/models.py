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

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q
from pgvector.django import VectorField


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

    `h_index` and `h_index_normalized` are computed reputation signals
    (issue #11) derived from this author's papers' `cited_by_count` and
    `publication_year`. They are stored rather than computed on read
    because recomputation is its own concern (#14/#28); see
    `papers.scoring` for the computation itself.
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
    h_index = models.PositiveIntegerField(default=0)
    h_index_normalized = models.FloatField(default=0.0)

    def __str__(self) -> str:
        return self.name


class Venue(models.Model):
    """Where a paper was published, as identified by OpenAlex."""

    name = models.CharField(max_length=500)
    openalex_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    def __str__(self) -> str:
        return self.name


class Paper(models.Model):
    """A paper/publication."""

    title = models.TextField()
    publication_year = models.PositiveIntegerField(null=True, blank=True)
    doi = models.CharField(max_length=255, null=True, blank=True, unique=True)
    abstract = models.TextField(null=True, blank=True)
    openalex_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    # OpenAlex always returns an integer here (confirmed live, see issue
    # #34), so this is not nullable. `counts_by_year` stores OpenAlex's
    # array of `{"year": int, "cited_by_count": int}` objects verbatim —
    # a rolling recent-years window, not full lifetime history (issue
    # #34's Constraints).
    cited_by_count = models.PositiveIntegerField(default=0)
    counts_by_year = models.JSONField(default=list)
    # `citations per year since publication` (issue #12): `cited_by_count`
    # divided by years elapsed since `publication_year`, or `0.0` when
    # `publication_year` is unknown. Stored rather than computed on read
    # for the same reason as `Author.h_index_normalized` (#11) —
    # recomputation is its own concern (#14/#28); see `papers.scoring`.
    citation_velocity = models.FloatField(default=0.0)
    # Combined-score sub-signals and final ranking value (issue #13):
    # `author_reputation_score` is the first author's `h_index_normalized`
    # rescaled to 0-100; `velocity_score` is `citation_velocity` rescaled
    # to 0-100; `combined_score` is their weighted sum. Stored (not
    # computed on read) for the same reason as `citation_velocity` above
    # -- recomputation is its own concern (#14/#28); see `papers.scoring`.
    author_reputation_score = models.FloatField(default=0.0)
    velocity_score = models.FloatField(default=0.0)
    combined_score = models.FloatField(default=0.0)
    # Semantic Scholar's SPECTER v2 embedding (issue #21), fetched and
    # stored by `fetch_semantic_scholar_embeddings` via
    # `semantic_scholar_client.get_papers`, keyed on `doi` — the only
    # realistic join key (#20's Constraints). `null=True`/`blank=True`
    # since a paper with no `doi`, or one Semantic Scholar has no record
    # for, has no embedding to store. 768 dimensions, matching #20's
    # confirmed-live `embedding.specter_v2` shape (not #3's smoke-test
    # `dimensions=3`). Stored here rather than computed on read so a
    # future similarity search (#23) is a DB query, not a live API call
    # per request.
    embedding = VectorField(dimensions=768, null=True, blank=True)
    # Semantic Scholar citation-influence data (issue #22):
    # `influential_citation_ratio` is `influential_citation_count /
    # citation_count` (both from Semantic Scholar), naturally bounded
    # 0.0-1.0; stored by `fetch_semantic_scholar_embeddings` alongside
    # `embedding`. `influential_citation_score` is that ratio rescaled to
    # 0-100, following the `citation_velocity`/`velocity_score`
    # raw/normalized naming pattern (#12/#13); only ever written by
    # `update_paper_combined_score`, never by the fetch command. Both
    # non-nullable with a `0.0` fallback -- unlike `embedding` above, a
    # ratio always has a defined value, so this follows the
    # `citation_velocity`/`velocity_score`/`author_reputation_score`
    # convention instead.
    influential_citation_ratio = models.FloatField(default=0.0)
    influential_citation_score = models.FloatField(default=0.0)
    venue = models.ForeignKey(
        Venue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="papers",
    )
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


class Citation(models.Model):
    """A directed citation edge: `citing_paper` cites `cited_paper`.

    Self-citation is blocked at the DB level (not just by convention) since
    ingestion (#9/#10) writes rows directly via the ORM rather than through a
    form, so a `clean()`-only validation would silently not run on that path
    (see issue #6's Constraints).
    """

    citing_paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="citations_made"
    )
    cited_paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="citations_received"
    )

    class Meta:
        unique_together = (("citing_paper", "cited_paper"),)
        constraints = [
            CheckConstraint(
                condition=~Q(citing_paper=models.F("cited_paper")),
                name="citation_no_self_citation",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.citing_paper.title} -> {self.cited_paper.title}"


class Follow(models.Model):
    """A signed-in user's subscription to track an `Author` or `Institution`.

    Per GitHub issue #25, this is one model (not separate `AuthorFollow`/
    `InstitutionFollow` models) with a `CheckConstraint` requiring exactly
    one of `author`/`institution` -- mirroring `Citation`'s self-citation
    `CheckConstraint` above (#6) -- so #26 (background polling) and #27
    (feed UI) have one table to query instead of two.

    `unique_together` on both `(user, author)` and `(user, institution)`
    prevents a user from following the same target twice; an
    author-follow row's `NULL` `institution` never collides with another
    row's `NULL` `institution` under Postgres's nullable-unique semantics
    (the same reasoning `Paper.doi` relies on, per #5's docstring).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="follows",
    )
    author = models.ForeignKey(
        Author,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    institution = models.ForeignKey(
        Institution,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="followers",
    )

    class Meta:
        unique_together = (
            ("user", "author"),
            ("user", "institution"),
        )
        constraints = [
            CheckConstraint(
                condition=(
                    Q(author__isnull=False, institution__isnull=True)
                    | Q(author__isnull=True, institution__isnull=False)
                ),
                name="follow_exactly_one_of_author_or_institution",
            ),
        ]

    def __str__(self) -> str:
        target = self.author or self.institution
        return f"{self.user} follows {target}"
