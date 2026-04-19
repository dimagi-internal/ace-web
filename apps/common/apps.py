from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    # No ready() hook — the Claude OAuth token is lazy-loaded on first use
    # via auth_flow.get_stored_token(), which reads the DB fresh on every
    # call and keeps the .credentials.json file on disk in sync for the
    # ``claude -p`` subprocess. Doing DB work in ready() triggered
    # "Accessing the database during app initialization" warnings and
    # tangled the pytest in-memory SQLite connection lifecycle.
