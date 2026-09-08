"""Model-level tests for the core domain schema.

Per GitHub issue #5: `Paper`, `Author`, `Institution`, and the ordered
`PaperAuthorship` through-model. These tests focus on the least-standard
part of the schema — the explicit through-model's ordering and uniqueness
constraints — since a bare M2M would not need this coverage.
"""

import pytest
from django.db import IntegrityError, transaction

from papers.models import (
    Author,
    Citation,
    Follow,
    Institution,
    Paper,
    PaperAuthorship,
    Venue,
)


@pytest.mark.django_db
def test_create_paper_author_institution():
    institution = Institution.objects.create(name="Aalto University")
    author = Author.objects.create(name="Ada Lovelace", institution=institution)
    paper = Paper.objects.create(title="On Computing Machinery", publication_year=2020)

    assert institution.pk is not None
    assert author.institution == institution
    assert paper.publication_year == 2020
    # Nullable fields default to None without being supplied.
    assert paper.doi is None
    assert paper.openalex_id is None
    assert author.openalex_id is None


@pytest.mark.django_db
def test_paper_authors_all_returns_ordered_by_position():
    paper = Paper.objects.create(title="Ordered Authors Paper")
    first_author = Author.objects.create(name="First Author")
    second_author = Author.objects.create(name="Second Author")

    # Create out of position order to prove ordering isn't an artifact of
    # insertion order.
    PaperAuthorship.objects.create(paper=paper, author=second_author, position=2)
    PaperAuthorship.objects.create(paper=paper, author=first_author, position=1)

    assert list(paper.authors.all()) == [first_author, second_author]


@pytest.mark.django_db
def test_paper_authorship_position_unique_per_paper():
    paper = Paper.objects.create(title="Position Clash Paper")
    author_a = Author.objects.create(name="Author A")
    author_b = Author.objects.create(name="Author B")

    PaperAuthorship.objects.create(paper=paper, author=author_a, position=1)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PaperAuthorship.objects.create(paper=paper, author=author_b, position=1)


@pytest.mark.django_db
def test_paper_authorship_paper_author_unique_together():
    paper = Paper.objects.create(title="Duplicate Author Paper")
    author = Author.objects.create(name="Repeat Author")

    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PaperAuthorship.objects.create(paper=paper, author=author, position=2)


@pytest.mark.django_db
def test_same_position_allowed_across_different_papers():
    paper_one = Paper.objects.create(title="Paper One")
    paper_two = Paper.objects.create(title="Paper Two")
    author = Author.objects.create(name="Shared Author")

    PaperAuthorship.objects.create(paper=paper_one, author=author, position=1)
    # Position 1 on a *different* paper is fine — the constraint is per-paper.
    PaperAuthorship.objects.create(paper=paper_two, author=author, position=1)

    assert paper_one.authors.count() == 1
    assert paper_two.authors.count() == 1


@pytest.mark.django_db
def test_nullable_unique_fields_allow_multiple_nulls():
    # Postgres allows multiple NULLs under a unique constraint, so
    # not-yet-matched rows (no OpenAlex ID yet) must not collide.
    Paper.objects.create(title="Paper Without OpenAlex ID 1")
    Paper.objects.create(title="Paper Without OpenAlex ID 2")
    Author.objects.create(name="Author Without OpenAlex ID 1")
    Author.objects.create(name="Author Without OpenAlex ID 2")

    assert Paper.objects.filter(openalex_id__isnull=True).count() == 2
    assert Author.objects.filter(openalex_id__isnull=True).count() == 2


@pytest.mark.django_db
def test_author_institution_set_null_on_institution_delete():
    institution = Institution.objects.create(name="Temporary Institution")
    author = Author.objects.create(name="Affiliated Author", institution=institution)

    institution.delete()
    author.refresh_from_db()

    assert author.institution is None


@pytest.mark.django_db
def test_str_representations():
    institution = Institution.objects.create(name="Aalto University")
    author = Author.objects.create(name="Ada Lovelace")
    paper = Paper.objects.create(title="On Computing Machinery", publication_year=2020)
    authorship = PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    assert str(institution) == "Aalto University"
    assert str(author) == "Ada Lovelace"
    assert str(paper) == "On Computing Machinery (2020)"
    assert "On Computing Machinery" in str(authorship)
    assert "Ada Lovelace" in str(authorship)


# --- Venue / Citation (issue #6) -------------------------------------------


@pytest.mark.django_db
def test_paper_venue_set_null_on_venue_delete():
    venue = Venue.objects.create(name="NeurIPS")
    paper = Paper.objects.create(title="A Paper in a Venue", venue=venue)

    assert venue.papers.count() == 1

    venue.delete()
    paper.refresh_from_db()

    assert paper.venue is None


@pytest.mark.django_db
def test_venue_nullable_openalex_id_allows_multiple_nulls():
    Venue.objects.create(name="Venue Without OpenAlex ID 1")
    Venue.objects.create(name="Venue Without OpenAlex ID 2")

    assert Venue.objects.filter(openalex_id__isnull=True).count() == 2


@pytest.mark.django_db
def test_citation_query_both_directions():
    # A cites B, C also cites B: two independent incoming edges on B, and
    # one outgoing edge each on A and C.
    paper_a = Paper.objects.create(title="Paper A")
    paper_b = Paper.objects.create(title="Paper B")
    paper_c = Paper.objects.create(title="Paper C")

    Citation.objects.create(citing_paper=paper_a, cited_paper=paper_b)
    Citation.objects.create(citing_paper=paper_c, cited_paper=paper_b)

    # "papers cited by A" - A's outgoing references.
    cited_by_a = {row.cited_paper for row in paper_a.citations_made.all()}
    assert cited_by_a == {paper_b}

    # "papers citing B" - B's incoming citations.
    citing_b = {row.citing_paper for row in paper_b.citations_received.all()}
    assert citing_b == {paper_a, paper_c}


@pytest.mark.django_db
def test_citation_self_citation_raises_integrity_error():
    paper = Paper.objects.create(title="Self-Citing Paper")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Citation.objects.create(citing_paper=paper, cited_paper=paper)


@pytest.mark.django_db
def test_citation_duplicate_pair_raises_integrity_error():
    paper_a = Paper.objects.create(title="Duplicate Citing Paper")
    paper_b = Paper.objects.create(title="Duplicate Cited Paper")

    Citation.objects.create(citing_paper=paper_a, cited_paper=paper_b)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Citation.objects.create(citing_paper=paper_a, cited_paper=paper_b)


@pytest.mark.django_db
def test_venue_and_citation_str_representations():
    venue = Venue.objects.create(name="NeurIPS")
    paper_a = Paper.objects.create(title="Citing Paper")
    paper_b = Paper.objects.create(title="Cited Paper")
    citation = Citation.objects.create(citing_paper=paper_a, cited_paper=paper_b)

    assert str(venue) == "NeurIPS"
    assert str(citation) == "Citing Paper -> Cited Paper"


# --- Follow (issue #25) ------------------------------------------------


@pytest.mark.django_db
def test_follow_author_and_institution(django_user_model):
    user = django_user_model.objects.create_user(username="alice", password="pw")
    author = Author.objects.create(name="Ada Lovelace")
    institution = Institution.objects.create(name="Aalto University")

    author_follow = Follow.objects.create(user=user, author=author)
    institution_follow = Follow.objects.create(user=user, institution=institution)

    assert author_follow.author == author
    assert author_follow.institution is None
    assert institution_follow.institution == institution
    assert institution_follow.author is None
    assert set(user.follows.all()) == {author_follow, institution_follow}


@pytest.mark.django_db
def test_follow_check_constraint_rejects_neither_author_nor_institution(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="bob", password="pw")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Follow.objects.create(user=user)


@pytest.mark.django_db
def test_follow_check_constraint_rejects_both_author_and_institution(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="carol", password="pw")
    author = Author.objects.create(name="Ada Lovelace")
    institution = Institution.objects.create(name="Aalto University")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Follow.objects.create(user=user, author=author, institution=institution)


@pytest.mark.django_db
def test_follow_unique_together_prevents_duplicate_author_follow(django_user_model):
    user = django_user_model.objects.create_user(username="dave", password="pw")
    author = Author.objects.create(name="Ada Lovelace")
    Follow.objects.create(user=user, author=author)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Follow.objects.create(user=user, author=author)


@pytest.mark.django_db
def test_follow_unique_together_prevents_duplicate_institution_follow(
    django_user_model,
):
    user = django_user_model.objects.create_user(username="erin", password="pw")
    institution = Institution.objects.create(name="Aalto University")
    Follow.objects.create(user=user, institution=institution)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Follow.objects.create(user=user, institution=institution)


@pytest.mark.django_db
def test_follow_nullable_unique_allows_one_author_and_one_institution_follow_per_user(
    django_user_model,
):
    # A row's NULL institution (author-follow) never collides with
    # another row's NULL author (institution-follow) under Postgres's
    # nullable-unique semantics -- both belong to the same user.
    user = django_user_model.objects.create_user(username="frank", password="pw")
    author = Author.objects.create(name="Ada Lovelace")
    institution = Institution.objects.create(name="Aalto University")

    Follow.objects.create(user=user, author=author)
    Follow.objects.create(user=user, institution=institution)

    assert Follow.objects.filter(user=user).count() == 2


@pytest.mark.django_db
def test_follow_str_representation(django_user_model):
    user = django_user_model.objects.create_user(username="grace", password="pw")
    author = Author.objects.create(name="Ada Lovelace")
    institution = Institution.objects.create(name="Aalto University")

    author_follow = Follow.objects.create(user=user, author=author)
    institution_follow = Follow.objects.create(user=user, institution=institution)

    assert "Ada Lovelace" in str(author_follow)
    assert "Aalto University" in str(institution_follow)
