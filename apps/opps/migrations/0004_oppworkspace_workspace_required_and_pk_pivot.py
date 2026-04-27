"""OppWorkspace PK pivot — Phase B foundation.

Pivots `OppWorkspace.slug` from being the primary key (globally unique) to
being a non-PK column (unique-per-workspace). A synthetic `id` BigAutoField
becomes the new primary key. The `workspace` FK becomes non-nullable.

Data prerequisite: every existing OppWorkspace row already has
`workspace_id` populated by `ace_workspaces.0002_seed_dimagi_team`, so the
not-null alteration is a no-op data-wise.

Uses Django's standard schema-editor operations (no raw SQL) so it
works on both SQLite (tests) and Postgres (prod). On SQLite, Django
rebuilds the table; on Postgres, it issues ALTER TABLE statements.
"""
from django.db import migrations, models


def _assert_workspace_populated(apps, schema_editor):
    """Guard: refuse to run the pivot if any row has a NULL workspace.

    The seed migration should have populated all rows. If this assertion
    fires, the seed migration didn't run (e.g. test env with no
    `ACE_DRIVE_ROOT_FOLDER_ID`) — the pivot is harmless on an empty table,
    so we only fail when data exists with NULLs.
    """
    OppWorkspace = apps.get_model("opps", "OppWorkspace")
    null_count = OppWorkspace.objects.filter(workspace__isnull=True).count()
    if null_count > 0:
        raise RuntimeError(
            f"{null_count} OppWorkspace rows have workspace=NULL. "
            "Run the ace_workspaces.0002_seed_dimagi_team migration first, "
            "or set ACE_DRIVE_ROOT_FOLDER_ID before migrating."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("opps", "0003_oppworkspace_workspace"),
        ("ace_workspaces", "0002_seed_dimagi_team"),
    ]

    operations = [
        migrations.RunPython(
            _assert_workspace_populated,
            reverse_code=migrations.RunPython.noop,
        ),
        # 1) Drop slug as the primary key. Django needs a stand-in PK
        #    first, so add the synthetic id and demote slug in the same
        #    operation. We use RemoveField + AddField instead of in-place
        #    edits because Django's SchemaEditor handles the table
        #    rebuild cleanly on SQLite that way.
        migrations.AlterField(
            model_name="oppworkspace",
            name="slug",
            field=models.CharField(max_length=64, primary_key=False),
        ),
        migrations.AddField(
            model_name="oppworkspace",
            name="id",
            field=models.BigAutoField(
                auto_created=True, primary_key=True, serialize=False,
                verbose_name="ID",
            ),
        ),
        # 2) Tighten workspace_id to NOT NULL. The seed migration
        #    populated every row, so this is a structural-only change.
        migrations.AlterField(
            model_name="oppworkspace",
            name="workspace",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="opps",
                to="ace_workspaces.workspace",
            ),
        ),
        # 3) Add the (workspace, slug) UNIQUE constraint.
        migrations.AlterUniqueTogether(
            name="oppworkspace",
            unique_together={("workspace", "slug")},
        ),
        # 4) Index slug for the legacy lookups still in flight.
        migrations.AddIndex(
            model_name="oppworkspace",
            index=models.Index(fields=["slug"], name="opp_workspa_slug_925a38_idx"),
        ),
    ]
