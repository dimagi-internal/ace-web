"""Drop the retired Slack integration's tables.

`apps.slack` was removed (Jonathan, 2026-10-08: Slack is "handled by canopy").
Removing an app from INSTALLED_APPS leaves its tables behind, so drop them here,
along with the app's migration history and content types. Idempotent
(IF EXISTS), and irreversible by design.
"""
from django.db import migrations

TABLES = ("slack_run_threads", "slack_user_links", "slack_installations")
APP_LABEL = "ace_slack"


def drop(apps, schema_editor):
    conn = schema_editor.connection
    with conn.cursor() as cur:
        for table in TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {conn.ops.quote_name(table)}")
        cur.execute("DELETE FROM django_migrations WHERE app = %s", [APP_LABEL])
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.filter(app_label=APP_LABEL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0008_drop_labs_allowed_domains"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
