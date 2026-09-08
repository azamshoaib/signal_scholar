"""Tests for the Semantic Scholar API client.

Per GitHub issue #20: no live network calls — every `requests.get`/
`requests.post` call is mocked via `unittest.mock.patch`, mirroring #8's
test approach for `openalex_client`. The mocked response bodies below are
structurally faithful to the real, live shape Semantic Scholar returned
while grooming issue #20 (`paperId`, `externalIds.DOI`,
`citationCount`/`influentialCitationCount` as plain top-level ints,
`tldr.text`, and `embedding.specter_v2` as a 768-dim `{"model", "vector"}`
object).
"""

from __future__ import annotations

import os
from unittest.mock import Mock, patch

import pytest
import requests

from semantic_scholar_client import (
    SemanticScholarClientError,
    SemanticScholarPaper,
    get_paper,
    get_papers,
)

_SAMPLE_VECTOR = [round(0.001 * i, 6) for i in range(768)]


def _make_response(json_body, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_body
    return response


def _sample_paper(
    paper_id: str = "a5de30adc5c22bc86e8cfabe7fbd07c052d196a8",
    doi: str = "10.1038/nature12373",
    title: str = "A landmark paper",
) -> dict:
    """A real-shaped Semantic Scholar `paper` object."""
    return {
        "paperId": paper_id,
        "externalIds": {"DOI": doi, "CorpusId": 12345},
        "title": title,
        "citationCount": 1817,
        "influentialCitationCount": 26,
        "tldr": {"model": "tldr@v2.0.0", "text": "A short summary."},
        "embedding": {"model": "specter_v2", "vector": _SAMPLE_VECTOR},
    }


class TestGetPaper:
    @patch("semantic_scholar_client.client.requests.get")
    def test_success_parses_expected_fields(self, mock_get):
        mock_get.return_value = _make_response(_sample_paper())

        paper = get_paper("10.1038/nature12373")

        assert paper == SemanticScholarPaper(
            semantic_scholar_id="a5de30adc5c22bc86e8cfabe7fbd07c052d196a8",
            doi="10.1038/nature12373",
            title="A landmark paper",
            citation_count=1817,
            influential_citation_count=26,
            embedding=_SAMPLE_VECTOR,
            tldr="A short summary.",
        )
        assert len(paper.embedding) == 768

        # Confirms the request hit the DOI-prefixed single-paper endpoint
        # with the bare DOI the caller passed in (no double-prefixing),
        # and requested the v2 embedding explicitly.
        called_url = mock_get.call_args.args[0]
        assert called_url == (
            "https://api.semanticscholar.org/graph/v1/paper/"
            "DOI:10.1038/nature12373"
        )
        params = mock_get.call_args.kwargs["params"]
        assert "embedding.specter_v2" in params["fields"]

    @patch("semantic_scholar_client.client.requests.get")
    def test_null_embedding_and_tldr_parse_to_none(self, mock_get):
        paper_json = _sample_paper()
        paper_json["embedding"] = None
        paper_json["tldr"] = None
        mock_get.return_value = _make_response(paper_json)

        paper = get_paper("10.1038/nature12373")

        assert paper.embedding is None
        assert paper.tldr is None

    @patch("semantic_scholar_client.client.requests.get")
    def test_malformed_embedding_degrades_to_none_instead_of_raising(self, mock_get):
        paper_json = _sample_paper()
        paper_json["embedding"] = {"model": "specter_v2", "vector": "not a list"}
        mock_get.return_value = _make_response(paper_json)

        paper = get_paper("10.1038/nature12373")

        assert paper.embedding is None

    @patch("semantic_scholar_client.client.requests.get")
    def test_missing_doi_in_response_parses_to_none(self, mock_get):
        paper_json = _sample_paper()
        del paper_json["externalIds"]
        mock_get.return_value = _make_response(paper_json)

        paper = get_paper("10.1038/nature12373")

        assert paper.doi is None

    @patch("semantic_scholar_client.client.requests.get")
    def test_not_found_raises_client_error_with_404(self, mock_get):
        mock_get.return_value = _make_response({"error": "Paper not found"}, status_code=404)

        with pytest.raises(SemanticScholarClientError) as exc_info:
            get_paper("10.9999/does-not-exist")

        assert exc_info.value.status_code == 404

    @patch("semantic_scholar_client.client.requests.get")
    def test_rate_limit_raises_client_error_with_429(self, mock_get):
        mock_get.return_value = _make_response(
            {"message": "Too Many Requests...", "code": "429"}, status_code=429
        )

        with pytest.raises(SemanticScholarClientError) as exc_info:
            get_paper("10.1038/nature12373")

        assert exc_info.value.status_code == 429

    @patch("semantic_scholar_client.client.requests.get")
    def test_network_exception_raises_client_error_with_no_status_code(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("boom")

        with pytest.raises(SemanticScholarClientError) as exc_info:
            get_paper("10.1038/nature12373")

        assert exc_info.value.status_code is None

    @patch.dict(os.environ, {}, clear=False)
    @patch("semantic_scholar_client.client.requests.get")
    def test_no_api_key_env_var_sends_no_auth_header(self, mock_get):
        os.environ.pop("SEMANTIC_SCHOLAR_API_KEY", None)
        mock_get.return_value = _make_response(_sample_paper())

        get_paper("10.1038/nature12373")

        headers = mock_get.call_args.kwargs["headers"]
        assert "x-api-key" not in headers

    @patch.dict(os.environ, {"SEMANTIC_SCHOLAR_API_KEY": "test-key-123"})
    @patch("semantic_scholar_client.client.requests.get")
    def test_api_key_env_var_sent_as_header(self, mock_get):
        mock_get.return_value = _make_response(_sample_paper())

        get_paper("10.1038/nature12373")

        headers = mock_get.call_args.kwargs["headers"]
        assert headers["x-api-key"] == "test-key-123"


class TestGetPapers:
    @patch("semantic_scholar_client.client.requests.post")
    def test_success_positionally_aligned_with_none_for_unmatched(self, mock_post):
        matched = _sample_paper(doi="10.1038/nature12373")
        mock_post.return_value = _make_response([matched, None])

        results = get_papers(["10.1038/nature12373", "10.9999/does-not-exist"])

        assert len(results) == 2
        assert isinstance(results[0], SemanticScholarPaper)
        assert results[0].doi == "10.1038/nature12373"
        assert results[1] is None

        called_url = mock_post.call_args.args[0]
        assert called_url == "https://api.semanticscholar.org/graph/v1/paper/batch"
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body == {
            "ids": ["DOI:10.1038/nature12373", "DOI:10.9999/does-not-exist"]
        }

    def test_empty_input_returns_empty_list_without_any_request(self):
        with patch("semantic_scholar_client.client.requests.post") as mock_post:
            results = get_papers([])

        assert results == []
        mock_post.assert_not_called()

    @patch("semantic_scholar_client.client.requests.post")
    def test_non_2xx_response_raises_client_error(self, mock_post):
        mock_post.return_value = _make_response(
            {"message": "Too Many Requests...", "code": "429"}, status_code=429
        )

        with pytest.raises(SemanticScholarClientError) as exc_info:
            get_papers(["10.1038/nature12373"])

        assert exc_info.value.status_code == 429

    @patch("semantic_scholar_client.client.requests.post")
    def test_network_exception_raises_client_error_with_no_status_code(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timed out")

        with pytest.raises(SemanticScholarClientError) as exc_info:
            get_papers(["10.1038/nature12373"])

        assert exc_info.value.status_code is None

    @patch("semantic_scholar_client.client.requests.post")
    def test_response_length_mismatch_raises_client_error(self, mock_post):
        mock_post.return_value = _make_response([_sample_paper()])

        with pytest.raises(SemanticScholarClientError):
            get_papers(["10.1038/nature12373", "10.1234/other"])
