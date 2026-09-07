"""Regression check for the pgvector extension + Django integration.

Per GitHub issue #3, this proves that a `pgvector.django.VectorField`
column round-trips correctly against the pgvector-enabled Postgres
container. This test, its model (`pgvector_setup.VectorSmokeTest`), and
its migrations are meant to stay in the repo permanently, the same way
the trivial test from #1 stayed in place as a standing check on the
Django setup.
"""

import pytest

from pgvector_setup.models import VectorSmokeTest


@pytest.mark.django_db
def test_vector_field_round_trips():
    created = VectorSmokeTest.objects.create(embedding=[1.0, 2.0, 3.0])

    reloaded = VectorSmokeTest.objects.get(pk=created.pk)

    assert list(reloaded.embedding) == [1.0, 2.0, 3.0]
