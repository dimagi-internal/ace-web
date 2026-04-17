from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    # No ready() hook — the Claude OAuth token is lazy-loaded on first use
    # via auth_flow.get_stored_token(), which pulls from the DB and caches
    # into the CLAUDE_CODE_OAUTH_TOKEN env var. Doing DB work in ready()
    # triggered "Accessing the database during app initialization" warnings
    # and tangled the pytest in-memory SQLite connection lifecycle.
