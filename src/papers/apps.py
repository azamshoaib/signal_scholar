from django.apps import AppConfig


class PapersConfig(AppConfig):
    """Core domain models for the SignalScholar schema.

    See GitHub issue #5. `Paper`, `Author`, `Institution`, and the
    `PaperAuthorship` through-model live here. #6 adds `Venue` and
    `Citation` to this same app, and #7 registers all five models with
    the admin.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "papers"
