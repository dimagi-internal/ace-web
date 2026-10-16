"""`RunClone.id_map` + `files_resumed`: a failed clone resumes (ace-web#864).

A re-POST over an errored clone used to trash the partial target and start
from file 0; clone record 3 died at file 851 (~25 min) on one Drive 500. The
source->copy id map is now persisted so the next attempt skips what landed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ace_workspaces", "0013_remove_auto_join_domains"),
    ]

    operations = [
        migrations.AddField(
            model_name="runclone",
            name="files_resumed",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="runclone",
            name="id_map",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
