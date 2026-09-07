from django.apps import AppConfig


class PgvectorSetupConfig(AppConfig):
    """Enables the pgvector extension and proves it works end to end.

    See GitHub issue #3. This app exists solely to enable the Postgres
    `vector` extension and to hold a small smoke-test model
    (`VectorSmokeTest`) that proves `pgvector.django.VectorField` can be
    created, migrated, and round-tripped against it. It is not one of the
    future domain-model apps, and its model is not extended by later work.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "pgvector_setup"
