"""Back-fill: ensure every Session has a SessionParticipant row for its
owner. Previously, opps-side paths (opp_creator, working-session lazy
creation, discuss-in-chat, fork) created sessions without the owner row,
which made the sessions invisible to their own owner via
/api/sessions/<slug> — the Workbench chat pane hung on "Loading chat…".
The code paths are now fixed to use Session.create_with_owner, but any
sessions that pre-date the fix still need the participant row."""

from django.db import migrations


def add_owner_participants(apps, schema_editor):
    Session = apps.get_model("ace_sessions", "Session")
    SessionParticipant = apps.get_model("ace_sessions", "SessionParticipant")
    for session_id, owner_id in Session.objects.values_list("id", "owner_id"):
        SessionParticipant.objects.get_or_create(
            session_id=session_id,
            user_id=owner_id,
            defaults={"role": "owner"},
        )


def noop_reverse(apps, schema_editor):
    # Don't remove participants on reverse — other participants may have
    # been added later and we can't distinguish them here.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ace_sessions", "0002_session_opp_pointers"),
    ]
    operations = [
        migrations.RunPython(add_owner_participants, noop_reverse),
    ]
