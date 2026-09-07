from django.db import models
from pgvector.django import VectorField


class VectorSmokeTest(models.Model):
    """Disposable-in-purpose, permanent-in-repo regression check.

    Proves that a fixed-dimension `pgvector.django.VectorField` can be
    created, migrated, and read/written against the pgvector-enabled
    Postgres container. See GitHub issue #3. Not a domain model: future
    issues (#5, #6, #21) do not build on this model.
    """

    embedding = VectorField(dimensions=3)
