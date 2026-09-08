"""Tests for the `GET /feed/` personalized feed page (GitHub issue #27).

Mirrors `tests/test_papers_detail_page.py`'s hand-built-fixture-plus-
Django-test-`client` approach: no live OpenAlex calls, `Follow` rows and
`Paper`/`Author`/`Institution`/`Venue`/`PaperAuthorship` fixtures built
directly via the ORM.
"""

from __future__ import annotations

import pytest

from papers.models import Author, Follow, Institution, Paper, PaperAuthorship, Venue

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="s3cret-pw!")


def _login(client):
    client.login(username="alice", password="s3cret-pw!")


# --- Auth gating ---------------------------------------------------------


def test_unauthenticated_get_feed_redirects_to_login(client):
    response = client.get("/feed/")

    assert response.status_code == 302
    assert response.url == "/login/?next=/feed/"


# --- Empty states ----------------------------------------------------------


def test_user_following_no_one_sees_empty_state_a(client, user):
    _login(client)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "You aren't following any authors or institutions yet." in body


def test_user_following_someone_with_no_matching_papers_sees_empty_state_b(
    client, user
):
    _login(client)
    author = Author.objects.create(name="Ada Lovelace")
    Follow.objects.create(user=user, author=author)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "None of the authors or institutions you follow have any papers yet." in body
    assert "You aren't following any authors or institutions yet." not in body


# --- Matching ---------------------------------------------------------------


def test_paper_by_followed_author_at_any_position_appears(client, user):
    _login(client)
    followed_author = Author.objects.create(name="Grace Hopper")
    other_author = Author.objects.create(name="Margaret Hamilton")
    Follow.objects.create(user=user, author=followed_author)

    paper = Paper.objects.create(title="A paper with a followed co-author")
    # followed_author is *not* first author (position 2).
    PaperAuthorship.objects.create(paper=paper, author=other_author, position=1)
    PaperAuthorship.objects.create(paper=paper, author=followed_author, position=2)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "A paper with a followed co-author" in body


def test_paper_by_author_at_followed_institution_appears_even_at_non_first_position(
    client, user
):
    _login(client)
    institution = Institution.objects.create(name="Aalto University")
    Follow.objects.create(user=user, institution=institution)

    author_at_institution = Author.objects.create(
        name="Grace Hopper", institution=institution
    )
    other_author = Author.objects.create(name="Margaret Hamilton")

    paper = Paper.objects.create(title="A paper via a followed institution")
    PaperAuthorship.objects.create(paper=paper, author=other_author, position=1)
    PaperAuthorship.objects.create(
        paper=paper, author=author_at_institution, position=2
    )

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "A paper via a followed institution" in body


def test_paper_matching_both_author_and_institution_follow_appears_once(client, user):
    _login(client)
    institution = Institution.objects.create(name="Aalto University")
    followed_author = Author.objects.create(name="Grace Hopper")
    author_at_institution = Author.objects.create(
        name="Margaret Hamilton", institution=institution
    )
    Follow.objects.create(user=user, author=followed_author)
    Follow.objects.create(user=user, institution=institution)

    paper = Paper.objects.create(title="A doubly-matching paper")
    PaperAuthorship.objects.create(paper=paper, author=followed_author, position=1)
    PaperAuthorship.objects.create(
        paper=paper, author=author_at_institution, position=2
    )

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert body.count("A doubly-matching paper") == 1


def test_paper_matching_neither_follow_does_not_appear(client, user):
    _login(client)
    followed_author = Author.objects.create(name="Grace Hopper")
    Follow.objects.create(user=user, author=followed_author)

    unrelated_author = Author.objects.create(name="Unrelated Author")
    paper = Paper.objects.create(title="An unrelated paper")
    PaperAuthorship.objects.create(paper=paper, author=unrelated_author, position=1)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "An unrelated paper" not in body
    assert "None of the authors or institutions you follow have any papers yet." in body


# --- Ordering ----------------------------------------------------------------


def test_ordering_is_publication_year_desc_with_nulls_last(client, user):
    _login(client)
    author = Author.objects.create(name="Grace Hopper")
    Follow.objects.create(user=user, author=author)

    older = Paper.objects.create(title="Older paper", publication_year=2010)
    newer = Paper.objects.create(title="Newer paper", publication_year=2020)
    unknown_year = Paper.objects.create(title="Unknown-year paper", publication_year=None)
    for paper in (older, newer, unknown_year):
        PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/feed/")
    body = response.content.decode()

    newer_pos = body.index("Newer paper")
    older_pos = body.index("Older paper")
    unknown_pos = body.index("Unknown-year paper")

    # Newest year first; the null-year paper sorts *last*, not first --
    # this is the specific bug a naive `-publication_year` would produce
    # under Postgres's default NULLS FIRST DESC ordering.
    assert newer_pos < older_pos < unknown_pos


# --- Limit / summary line -----------------------------------------------------


def test_summary_line_shows_count_when_not_truncated(client, user):
    _login(client)
    author = Author.objects.create(name="Grace Hopper")
    Follow.objects.create(user=user, author=author)
    paper = Paper.objects.create(title="Only paper")
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/feed/")
    body = response.content.decode()

    assert "Showing 1 of 1 papers." in body


def test_feed_is_capped_at_default_limit_with_correct_summary_line(client, user):
    from papers.services import DEFAULT_LIMIT

    _login(client)
    author = Author.objects.create(name="Grace Hopper")
    Follow.objects.create(user=user, author=author)

    total_papers = DEFAULT_LIMIT + 5
    for i in range(total_papers):
        paper = Paper.objects.create(title=f"Paper {i}", publication_year=2000 + i)
        PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert f"Showing {DEFAULT_LIMIT} of {total_papers} papers." in body


# --- Score breakdown reuse -----------------------------------------------------


def test_score_breakdown_include_renders_full_breakdown_on_feed_card(client, user):
    # Mirrors tests/test_papers_detail_page.py's
    # test_score_breakdown_shows_hand_computed_values fixture.
    venue = Venue.objects.create(name="ICML")
    followed_author = Author.objects.create(name="Grace Hopper", h_index_normalized=2.5)
    other_author = Author.objects.create(name="Margaret Hamilton")
    paper = Paper.objects.create(
        title="Compiler design principles",
        venue=venue,
        publication_year=2015,
        citation_velocity=25.0,
        influential_citation_ratio=0.4,
        author_reputation_score=50.0,
        velocity_score=50.0,
        influential_citation_score=40.0,
        combined_score=46.7,
    )
    PaperAuthorship.objects.create(paper=paper, author=followed_author, position=1)
    PaperAuthorship.objects.create(paper=paper, author=other_author, position=2)

    _login(client)
    Follow.objects.create(user=user, author=followed_author)

    response = client.get("/feed/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Grace Hopper" in body
    assert "2.5" in body
    assert "50.0" in body
    assert "25.0" in body
    assert "0.4" in body
    assert "40.0" in body
    assert "Combined score: 46.7" in body
    assert (
        "Combined score = 34% author reputation + 33% citation velocity "
        "+ 33% highly-influential-citation ratio." in body
    )


def test_feed_card_title_links_to_detail_page(client, user):
    author = Author.objects.create(name="Grace Hopper")
    paper = Paper.objects.create(title="A linked paper")
    PaperAuthorship.objects.create(paper=paper, author=author, position=1)

    _login(client)
    Follow.objects.create(user=user, author=author)

    response = client.get("/feed/")
    body = response.content.decode()

    assert f'href="/papers/{paper.id}/"' in body


# --- N+1 avoidance -------------------------------------------------------------


# Session lookup + user lookup (2, from @login_required's auth
# middleware) + Follow.exists() (1) + queryset.count() (1) + the main
# SELECT with select_related join (1, no extra query) + 2 prefetch
# queries for authorships__author (one for authorships, one for their
# authors) -- a fixed cost regardless of how many matching papers there
# are, not one extra query per paper (which would be the N+1 bug #14
# already had to fix once for search_papers, guarded against here too).
EXPECTED_FEED_QUERY_COUNT = 7


def _build_matching_papers_for_user(user, *, num_papers: int) -> None:
    venue = Venue.objects.create(name="Venue A")
    followed_author = Author.objects.create(name="Followed Author")
    Follow.objects.create(user=user, author=followed_author)
    for i in range(num_papers):
        paper = Paper.objects.create(title=f"Matching paper {i}", venue=venue)
        PaperAuthorship.objects.create(paper=paper, author=followed_author, position=1)


def test_no_n_plus_one_query_growth_small_fixture(django_assert_num_queries, client, user):
    _build_matching_papers_for_user(user, num_papers=3)
    _login(client)

    with django_assert_num_queries(EXPECTED_FEED_QUERY_COUNT):
        client.get("/feed/")


def test_no_n_plus_one_query_growth_larger_fixture_same_query_count(
    django_assert_num_queries, client, user
):
    # 10x the papers of the small fixture above -- if the view had a real
    # N+1 (e.g. re-querying authorships per paper instead of reusing the
    # prefetch cache), this would blow past the fixed count the small
    # fixture also satisfies.
    _build_matching_papers_for_user(user, num_papers=30)
    _login(client)

    with django_assert_num_queries(EXPECTED_FEED_QUERY_COUNT):
        client.get("/feed/")
