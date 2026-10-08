from django.apps import AppConfig


class SiteAdminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.site_admin"
    label = "ace_site_admin"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registers the bootstrap receiver)
