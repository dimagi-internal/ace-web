# Drops the cloud mobile emulator's only table (retired 2026-10-14).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mobile", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="MobileLaunchScriptPatch",
        ),
    ]
