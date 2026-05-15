from django.apps import AppConfig


class SlackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.slack"
    label = "ace_slack"   # avoid colliding with any third-party "slack" app
    verbose_name = "Slack integration"

    def ready(self):
        # Skip during tests and migrate to avoid spurious worker spawns.
        import os
        import sys
        if os.environ.get("DJANGO_SLACK_DISABLE_WORKER") == "1":
            return
        if "pytest" in sys.modules or "test" in sys.argv or "migrate" in sys.argv:
            return
        from .dispatcher import start_worker
        start_worker()
