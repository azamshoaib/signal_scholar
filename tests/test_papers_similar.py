"""Tests for `GET /api/papers/{paper_id}/similar` (GitHub issue #23).

Uses Django's test `client` fixture (from pytest-django) to hit the real
Ninja-mounted endpoint end to end, and hand-constructed `Paper` fixtures
with real 768-dimension embedding vectors -- no mocking, no external API
involved (this is a pure DB/pgvector query, same spirit as
`tests/test_papers_embedding_field.py`'s direct, unmocked round-trip
test).
"""

from __future__ import annotations

import pytest
from pgvector.django import CosineDistance

from papers.models import Paper
from papers.services import CANDIDATE_POOL_SIZE


def _vec(*leading: float) -> list[float]:
    """Build a 768-dim vector: `leading` values, then zeros."""
    return list(leading) + [0.0] * (768 - len(leading))


@pytest.mark.django_db
def test_combined_score_reranks_similarity_order(client):
    # Source paper A.
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))
    # B: very close to A in cosine distance, but a LOW combined_score.
    b = Paper.objects.create(
        title="Candidate B - close but low score",
        embedding=_vec(0.99, 0.01),
        combined_score=10.0,
    )
    # C: farther from A than B, but a HIGH combined_score.
    c = Paper.objects.create(
        title="Candidate C - far but high score",
        embedding=_vec(0.7, 0.7),
        combined_score=90.0,
    )

    # Sanity: a plain nearest-neighbor query (no re-rank) would return
    # [B, C] -- B strictly closer than C -- proving the fixture actually
    # exercises a real reordering below, not a no-op.
    pure_similarity_order = list(
        Paper.objects.exclude(pk=a.pk)
        .filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", a.embedding))
        .order_by("distance", "id")
        .values_list("id", flat=True)
    )
    assert pure_similarity_order == [b.id, c.id]

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    data = response.json()
    assert data["source_paper_id"] == a.id
    ids_in_order = [r["id"] for r in data["results"]]
    # The combined_score re-rank flips the pure-similarity order: C (high
    # score) now outranks B (low score), despite B being closer to A.
    assert ids_in_order == [c.id, b.id]
    # A is never present in its own results.
    assert a.id not in ids_in_order


@pytest.mark.django_db
def test_null_embedding_paper_never_appears_despite_high_score(client):
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))
    Paper.objects.create(
        title="Candidate B",
        embedding=_vec(0.99, 0.01),
        combined_score=10.0,
    )
    # D has no embedding at all, so it cannot be a similarity candidate --
    # regardless of how high its combined_score is.
    Paper.objects.create(
        title="Paper D with no embedding",
        embedding=None,
        combined_score=1000.0,
    )

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    ids = {r["id"] for r in response.json()["results"]}
    assert "Paper D with no embedding" not in [
        Paper.objects.get(pk=i).title for i in ids
    ]


@pytest.mark.django_db
def test_pool_boundary_excludes_highest_score_paper_outside_top_n(client):
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))

    # N=20 filler papers, all with embeddings very close to A (distinct
    # small perturbations so each is inside the top-20 nearest
    # neighbors), and low-to-mid combined_score values.
    fillers = []
    for i in range(CANDIDATE_POOL_SIZE):
        offset = 0.0001 * (i + 1)
        filler = Paper.objects.create(
            title=f"Filler paper {i}",
            embedding=_vec(1.0 - offset, offset),
            combined_score=float(i),
        )
        fillers.append(filler)

    # Z: embedding deliberately far from A (orthogonal), so it ranks
    # outside the top-20 nearest neighbors -- but its combined_score is
    # the single highest of any paper in the test's data.
    z = Paper.objects.create(
        title="Paper Z - highest score but far away",
        embedding=_vec(0.0, 0.0, 1.0),
        combined_score=100000.0,
    )

    # Confirm the fixture actually places Z outside the top-N nearest
    # neighbors (i.e. the test fixture is doing what it claims).
    nearest_ids = list(
        Paper.objects.exclude(pk=a.pk)
        .filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", a.embedding))
        .order_by("distance", "id")
        .values_list("id", flat=True)[:CANDIDATE_POOL_SIZE]
    )
    assert z.id not in nearest_ids
    assert len(nearest_ids) == CANDIDATE_POOL_SIZE

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    data = response.json()
    ids = [r["id"] for r in data["results"]]
    # Z would rank first under a naive "sort the whole table by
    # combined_score" approach -- but it must be absent here, since the
    # two-stage design filters it out of the candidate pool entirely.
    assert z.id not in ids
    # Confirm the results actually came from the filler pool (proving the
    # re-rank step ran on real candidates, not an empty pool).
    filler_ids = {f.id for f in fillers}
    assert set(ids).issubset(filler_ids)
    assert len(ids) == 10


@pytest.mark.django_db
def test_nonexistent_source_paper_returns_404(client):
    response = client.get("/api/papers/999999/similar")

    assert response.status_code == 404


@pytest.mark.django_db
def test_source_paper_with_no_embedding_returns_422(client):
    paper = Paper.objects.create(title="Unembedded source paper", embedding=None)

    response = client.get(f"/api/papers/{paper.id}/similar")

    assert response.status_code == 422
    assert str(paper.id) in response.json()["detail"]


@pytest.mark.django_db
def test_404_and_422_have_distinguishable_detail_messages(client):
    unembedded = Paper.objects.create(title="Unembedded source paper", embedding=None)

    not_found_response = client.get("/api/papers/999999/similar")
    no_embedding_response = client.get(f"/api/papers/{unembedded.id}/similar")

    assert not_found_response.status_code == 404
    assert no_embedding_response.status_code == 422
    assert (
        not_found_response.json()["detail"] != no_embedding_response.json()["detail"]
    )


@pytest.mark.django_db
def test_fewer_than_result_count_candidates_returns_all_without_padding(client):
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))
    x = Paper.objects.create(
        title="Candidate X", embedding=_vec(0.99, 0.01), combined_score=5.0
    )
    y = Paper.objects.create(
        title="Candidate Y", embedding=_vec(0.9, 0.1), combined_score=50.0
    )

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    data = response.json()
    ids = [r["id"] for r in data["results"]]
    assert len(ids) == 2
    # Re-ranked by combined_score descending: Y (50.0) before X (5.0).
    assert ids == [y.id, x.id]


@pytest.mark.django_db
def test_similarity_score_is_one_minus_cosine_distance_not_rescaled(client):
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))
    b = Paper.objects.create(
        title="Candidate B", embedding=_vec(0.99, 0.01), combined_score=10.0
    )

    expected_distance = (
        Paper.objects.filter(pk=b.pk)
        .annotate(distance=CosineDistance("embedding", a.embedding))
        .values_list("distance", flat=True)
        .get()
    )

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["id"] == b.id
    assert result["similarity_score"] == pytest.approx(1 - expected_distance)
    # Not rescaled to 0-100 like combined_score/velocity_score/etc.
    assert -1.0 <= result["similarity_score"] <= 1.0


@pytest.mark.django_db
def test_response_shape_includes_similarity_score_alongside_search_fields(client):
    a = Paper.objects.create(title="Source paper A", embedding=_vec(1.0, 0.0))
    Paper.objects.create(
        title="Candidate B", embedding=_vec(0.99, 0.01), combined_score=10.0
    )

    response = client.get(f"/api/papers/{a.id}/similar")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"source_paper_id", "results"}
    result = data["results"][0]
    assert set(result.keys()) == {
        "id",
        "title",
        "publication_year",
        "doi",
        "venue_name",
        "first_author_name",
        "citation_velocity",
        "author_reputation_score",
        "velocity_score",
        "combined_score",
        "similarity_score",
    }
