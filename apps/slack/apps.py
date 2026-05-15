from django.apps import AppConfig


class SlackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.slack"
    label = "ace_slack"   # avoid colliding with any third-party "slack" app
    verbose_name = "Slack integration"

    def ready(self):
        # Dispatcher worker spawn is deferred until Task 13.
        pass
