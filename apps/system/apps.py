from django.apps import AppConfig


class SystemConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.system"
    label = "system"
    verbose_name = "ACE System Overview"
