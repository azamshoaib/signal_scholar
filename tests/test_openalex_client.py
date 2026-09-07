"""Tests for the OpenAlex API client.

Per GitHub issue #8: no live network calls — every `requests.get` call is
mocked via `unittest.mock.patch`. The mocked response bodies below are
trimmed but structurally faithful to a real, live response fetched from
`https://api.openalex.org/works/...` and `.../works?search=...&cursor=*`
while implementing this issue (full URLs for `id`/`doi`,
`primary_location.source` for venue, a word -> positions
`abstract_inverted_index`, and `meta.next_cursor` cursor pagination).
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from openalex_client import (
    OpenAlexAuthor,
    OpenAlexClientError,
    OpenAlexInstitution,
    OpenAlexVenue,
    OpenAlexWork,
    get_work,
    search_works,
)


def _make_response(json_body, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_body
    return response


def _sample_work(
    openalex_id: str = "https://openalex.org/W2741809807",
    title: str = "The state of OA",
) -> dict:
    """A trimmed but real-shaped OpenAlex `work` object."""
    return {
        "id": openalex_id,
        "doi": "https://doi.org/10.7717/peerj.4375",
        "title": title,
        "display_name": title,
        "publication_year": 2018,
        "primary_location": {
            "source": {
                "id": "https://openalex.org/S1983995261",
                "display_name": "PeerJ",
            },
        },
        "abstract_inverted_index": {
            "Despite": [0],
            "growing": [1],
            "interest": [2],
        },
        "authorships": [
            {
                "author_position": "first",
                "author": {
                    "id": "https://openalex.org/A5048491430",
                    "display_name": "Heather Piwowar",
                },
                "institutions": [
                    {
                        "id": "https://openalex.org/I4200000001",
                        "display_name": "OpenAlex",
                    },
                ],
            },
            {
                "author_position": "last",
                "author": {
                    "id": "https://openalex.org/A2894104583",
                    "display_name": "Jason Priem",
                },
                "institutions": [],
            },
        ],
    }


class TestGetWork:
    @patch("openalex_client.client.requests.get")
    def test_success_parses_expected_fields(self, mock_get):
        mock_get.return_value = _make_response(_sample_work())

        work = get_work("W2741809807")

        assert work == OpenAlexWork(
            openalex_id="W2741809807",
            title="The state of OA",
            publication_year=2018,
            doi="10.7717/peerj.4375",
            abstract="Despite growing interest",
            venue=OpenAlexVenue(openalex_id="S1983995261", name="PeerJ"),
            authors=[
                OpenAlexAuthor(
                    openalex_id="A5048491430",
                    name="Heather Piwowar",
                    institutions=[
                        OpenAlexInstitution(openalex_id="I4200000001", name="OpenAlex"),
                    ],
                ),
                OpenAlexAuthor(openalex_id="A2894104583", name="Jason Priem", institutions=[]),
            ],
        )
        # Author order matches authorship position: index 0 is position 1.
        assert work.authors[0].name == "Heather Piwowar"
        assert work.authors[1].name == "Jason Priem"

        # Confirms the request hit the single-work endpoint with the
        # short-form ID the caller passed in.
        called_url = mock_get.call_args.args[0]
        assert called_url == "https://api.openalex.org/works/W2741809807"

    @patch("openalex_client.client.requests.get")
    def test_non_2xx_response_raises_client_error_with_status_code(self, mock_get):
        mock_get.return_value = _make_response({"error": "not found"}, status_code=404)

        with pytest.raises(OpenAlexClientError) as exc_info:
            get_work("W_DOES_NOT_EXIST")

        assert exc_info.value.status_code == 404

    @patch("openalex_client.client.requests.get")
    def test_network_exception_raises_client_error_with_no_status_code(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("boom")

        with pytest.raises(OpenAlexClientError) as exc_info:
            get_work("W2741809807")

        assert exc_info.value.status_code is None

    @patch("openalex_client.client.requests.get")
    def test_malformed_abstract_degrades_to_none_instead_of_raising(self, mock_get):
        work_json = _sample_work()
        # Not a word -> list-of-positions mapping.
        work_json["abstract_inverted_index"] = "not a dict"
        mock_get.return_value = _make_response(work_json)

        work = get_work("W2741809807")

        assert work.abstract is None

    @patch("openalex_client.client.requests.get")
    def test_missing_id_raises_client_error(self, mock_get):
        work_json = _sample_work()
        del work_json["id"]
        mock_get.return_value = _make_response(work_json)

        with pytest.raises(OpenAlexClientError) as exc_info:
            get_work("W2741809807")

        assert exc_info.value.status_code == 200


class TestSearchWorks:
    @patch("openalex_client.client.requests.get")
    def test_single_page_success(self, mock_get):
        body = {
            "meta": {"count": 2, "next_cursor": None},
            "results": [
                _sample_work("https://openalex.org/W1", "First Paper"),
                _sample_work("https://openalex.org/W2", "Second Paper"),
            ],
        }
        mock_get.return_value = _make_response(body)

        results = search_works("machine learning", max_results=25)

        assert [w.openalex_id for w in results] == ["W1", "W2"]
        assert [w.title for w in results] == ["First Paper", "Second Paper"]
        assert mock_get.call_count == 1

        params = mock_get.call_args.kwargs["params"]
        assert params["search"] == "machine learning"
        assert params["cursor"] == "*"

    @patch("openalex_client.client.requests.get")
    def test_follows_cursor_across_multiple_pages(self, mock_get):
        page_one = {
            "meta": {"count": 3, "next_cursor": "CURSOR_2"},
            "results": [_sample_work("https://openalex.org/W1", "First")],
        }
        page_two = {
            "meta": {"count": 3, "next_cursor": None},
            "results": [
                _sample_work("https://openalex.org/W2", "Second"),
                _sample_work("https://openalex.org/W3", "Third"),
            ],
        }
        mock_get.side_effect = [_make_response(page_one), _make_response(page_two)]

        results = search_works("machine learning", max_results=25)

        assert [w.openalex_id for w in results] == ["W1", "W2", "W3"]
        assert mock_get.call_count == 2

        first_call_cursor = mock_get.call_args_list[0].kwargs["params"]["cursor"]
        second_call_cursor = mock_get.call_args_list[1].kwargs["params"]["cursor"]
        assert first_call_cursor == "*"
        assert second_call_cursor == "CURSOR_2"

    @patch("openalex_client.client.requests.get")
    def test_stops_once_max_results_reached_without_extra_page_fetch(self, mock_get):
        page_one = {
            "meta": {"count": 100, "next_cursor": "CURSOR_2"},
            "results": [
                _sample_work("https://openalex.org/W1", "First"),
                _sample_work("https://openalex.org/W2", "Second"),
            ],
        }
        mock_get.return_value = _make_response(page_one)

        results = search_works("machine learning", max_results=1)

        assert len(results) == 1
        assert results[0].openalex_id == "W1"
        # Capped after the first page — no second page fetched.
        assert mock_get.call_count == 1

    @patch("openalex_client.client.requests.get")
    def test_non_2xx_response_raises_client_error(self, mock_get):
        mock_get.return_value = _make_response({"error": "server error"}, status_code=500)

        with pytest.raises(OpenAlexClientError) as exc_info:
            search_works("machine learning")

        assert exc_info.value.status_code == 500

    @patch("openalex_client.client.requests.get")
    def test_network_exception_raises_client_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("timed out")

        with pytest.raises(OpenAlexClientError) as exc_info:
            search_works("machine learning")

        assert exc_info.value.status_code is None

    def test_max_results_zero_returns_empty_list_without_any_request(self):
        with patch("openalex_client.client.requests.get") as mock_get:
            results = search_works("machine learning", max_results=0)

        assert results == []
        mock_get.assert_not_called()
