"""Drop the Slack integration's tables and forget its migration history.

`apps.slack` (the `/ace` slash command, the async dispatcher, run threads) was
removed from ace-web on 2026-10-08 — Jonathan: "remove slack settings and code
as well, its deprecated and handled by canopy." Slack for the fleet lives in
canopy now. Deleting the app deletes its migrations, so the tables it created
are dropped here, in an app that survives (children first: threads and user
links both point at installations).

`IF EXISTS` keeps this a no-op on a database that never had them (fresh
installs and test databases only ever build the tables from the migrations
that no longer exist). Reverse is a no-op: the data is not coming back.
"""
from django.db import migrations

DROP = """
DROP TABLE IF EXISTS slack_run_threads;
DROP TABLE IF EXISTS slack_user_links;
DROP TABLE IF EXISTS slack_installations;
DELETE FROM django_migrations WHERE app = 'slack';
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ace_workspaces", "0012_viewers_become_editors"),
    ]

    operations = [migrations.RunSQL(DROP, reverse_sql=migrations.RunSQL.noop)]
