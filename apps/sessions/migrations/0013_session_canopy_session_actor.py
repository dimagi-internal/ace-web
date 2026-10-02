from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ace_sessions", "0012_session_requested_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="canopy_session_actor",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
