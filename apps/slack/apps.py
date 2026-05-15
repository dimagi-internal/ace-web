from django.apps import AppConfig


class SlackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.slack"
    label = "ace_slack"   # avoid colliding with any third-party "slack" app
    verbose_name = "Slack integration"

    def ready(self):
        # Worker is started via the ASGI lifespan in config/asgi.py,
        # not here. No-op at Django app-load time.
        pass
