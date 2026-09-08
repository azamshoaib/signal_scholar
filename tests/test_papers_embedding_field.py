"""DB-level round-trip check for `Paper.embedding` (GitHub issue #21).

Mirrors #3's `VectorSmokeTest` round-trip test
(`tests/test_pgvector.py`), but against the real `Paper.embedding` field
directly -- no Semantic Scholar client, no mocking, no management command
involved. Proves the 768-dimension `pgvector.django.VectorField` added to
`Paper` by this issue writes and reads back correctly against the
pgvector-enabled Postgres container.
"""

from __future__ import annotations

import pytest

from papers.models import Paper

_SAMPLE_VECTOR = [round(0.001 * i, 6) for i in range(768)]


@pytest.mark.django_db
def test_paper_embedding_field_round_trips():
    created = Paper.objects.create(title="A paper with an embedding", embedding=_SAMPLE_VECTOR)

    reloaded = Paper.objects.get(pk=created.pk)

    assert len(reloaded.embedding) == 768
    assert list(reloaded.embedding) == _SAMPLE_VECTOR


@pytest.mark.django_db
def test_paper_embedding_defaults_to_none():
    created = Paper.objects.create(title="A paper with no embedding yet")

    reloaded = Paper.objects.get(pk=created.pk)

    assert reloaded.embedding is None
