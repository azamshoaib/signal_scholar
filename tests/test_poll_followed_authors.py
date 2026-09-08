"""Tests for the `poll_followed_authors` management command.

Per GitHub issue #26: `search_works_by_author` is patched at its import
site in the command module
(`papers.management.commands.poll_followed_authors.search_works_by_author`),
matching #8/#9's own mocking convention — no live network call.
`ingest_works` itself is *not* mocked in the created/updated-split and
zero-new-papers tests, so the real shared `papers.ingestion.ingest_works`
code path is actually exercised, per the issue's explicit "not a parallel
code path" requirement.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command

from openalex_client import OpenAlexWork
from papers.models import Author, Follow, Institution, Paper

pytestmark = pytest.mark.django_db


def _work(openalex_id: str, title: str = "A Paper") -> OpenAlexWork:
    return OpenAlexWork(
        openalex_id=openalex_id,
        title=title,
        publication_year=2024,
        doi=None,
        abstract=None,
        venue=None,
        authors=[],
    )


def _run(out: StringIO | None = None, **mock_kwargs) -> tuple[str, Mock]:
    stdout = out if out is not None else StringIO()
    with patch(
        "papers.management.commands.poll_followed_authors.search_works_by_author",
        **mock_kwargs,
    ) as mock_search:
        call_command("poll_followed_authors", stdout=stdout)
    return stdout.getvalue(), mock_search


@pytest.fixture
def alice(django_user_model):
    return django_user_model.objects.create_user(username="alice", password="pw")


@pytest.fixture
def bob(django_user_model):
    return django_user_model.objects.create_user(username="bob", password="pw")


def test_author_followed_by_two_users_polled_exactly_once(alice, bob):
    author = Author.objects.create(name="Ada Lovelace", openalex_id="A1")
    Follow.objects.create(user=alice, author=author)
    Follow.objects.create(user=bob, author=author)

    output, mock_search = _run(return_value=[])

    mock_search.assert_called_once_with("A1", max_results=25)
    assert "Followed authors (distinct): 1" in output
    assert "Authors polled: 1" in output
    assert "Authors skipped (no openalex_id): 0" in output


def test_author_with_no_openalex_id_is_skipped_and_never_queried(alice):
    author = Author.objects.create(name="No OpenAlex ID", openalex_id=None)
    Follow.objects.create(user=alice, author=author)

    output, mock_search = _run(return_value=[])

    mock_search.assert_not_called()
    assert "Followed authors (distinct): 1" in output
    assert "Authors skipped (no openalex_id): 1" in output
    assert "Authors polled: 0" in output


def test_mix_of_known_and_unseen_papers_produces_correct_created_updated_split(alice):
    author = Author.objects.create(name="Prolific Author", openalex_id="A1")
    Follow.objects.create(user=alice, author=author)
    # A paper OpenAlex will "re-return" that's already in the DB.
    Paper.objects.create(title="Already Known", openalex_id="W_KNOWN")

    fetched = [_work("W_KNOWN", "Already Known"), _work("W_NEW", "Brand New")]

    output, _ = _run(return_value=fetched)

    assert Paper.objects.filter(openalex_id="W_NEW").exists()
    assert Paper.objects.count() == 2
    assert "Papers created: 1" in output
    assert "Papers updated: 1" in output
    assert "Authors with zero new papers this run: 0" in output


def test_author_whose_poll_returns_only_known_papers_counts_as_zero_new(alice):
    author = Author.objects.create(name="Stale Author", openalex_id="A1")
    Follow.objects.create(user=alice, author=author)
    Paper.objects.create(title="Already Known", openalex_id="W_KNOWN")

    output, _ = _run(return_value=[_work("W_KNOWN", "Already Known")])

    assert Paper.objects.count() == 1
    assert "Papers created: 0" in output
    assert "Papers updated: 1" in output
    assert "Authors with zero new papers this run: 1" in output


def test_author_with_zero_openalex_works_counts_as_zero_new(alice):
    author = Author.objects.create(name="No Works Author", openalex_id="A1")
    Follow.objects.create(user=alice, author=author)

    output, _ = _run(return_value=[])

    assert "Papers created: 0" in output
    assert "Authors with zero new papers this run: 1" in output


def test_institution_only_follow_excluded_from_author_polling(alice):
    institution = Institution.objects.create(name="Aalto University")
    Follow.objects.create(user=alice, institution=institution)

    output, mock_search = _run(return_value=[])

    mock_search.assert_not_called()
    assert "Followed authors (distinct): 0" in output
    assert "Authors skipped (no openalex_id): 0" in output
    assert "Authors polled: 0" in output
    assert "Papers created: 0" in output
    assert "Papers updated: 0" in output
    assert "Authors with zero new papers this run: 0" in output


def test_user_follows_nothing_produces_report_of_all_zeros(alice):
    output, mock_search = _run(return_value=[])

    mock_search.assert_not_called()
    assert "Followed authors (distinct): 0" in output
    assert "Authors skipped (no openalex_id): 0" in output
    assert "Authors polled: 0" in output
    assert "Papers created: 0" in output
    assert "Papers updated: 0" in output
    assert "Authors with zero new papers this run: 0" in output


def test_max_results_per_author_option_passed_through(alice):
    author = Author.objects.create(name="Ada Lovelace", openalex_id="A1")
    Follow.objects.create(user=alice, author=author)

    with patch(
        "papers.management.commands.poll_followed_authors.search_works_by_author",
        return_value=[],
    ) as mock_search:
        call_command("poll_followed_authors", "--max-results-per-author", "5")

    mock_search.assert_called_once_with("A1", max_results=5)
