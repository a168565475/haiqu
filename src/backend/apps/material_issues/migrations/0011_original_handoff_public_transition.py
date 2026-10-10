import uuid

import django.db.models.deletion
from django.db import migrations, models


IMMUTABLE_SQL = """
CREATE FUNCTION protect_metal_original_public_transition() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '旧单接续凭证不允许修改或删除';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER metal_original_public_transition_immutable
BEFORE UPDATE OR DELETE ON metal_original_handoff_public_transition
FOR EACH ROW EXECUTE FUNCTION protect_metal_original_public_transition();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("material_issues", "0010_metalprocessingexternalgoodreturn_public_stock_movement_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="OriginalHandoffPublicTransition",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("source_hash", models.CharField(max_length=64)),
                ("handoff_snapshot_hash", models.CharField(max_length=64)),
                ("manifest_hash", models.CharField(max_length=64)),
                ("public_identity", models.JSONField()),
                ("evidence", models.JSONField()),
                ("quantity_snapshot", models.JSONField()),
                ("request_id", models.UUIDField(db_index=True)),
                ("request_payload_hash", models.CharField(max_length=64)),
                ("actor_employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organizations.employee")),
                ("original_handoff", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="public_transition", to="material_issues.metalprocessingoriginalhandoff")),
            ],
            options={
                "db_table": "metal_original_handoff_public_transition",
                "default_permissions": ("view",),
                "permissions": [("apply_originalhandoffpublictransition", "可在维护期接续旧金工直接交接")],
            },
        ),
        migrations.RunSQL(IMMUTABLE_SQL, reverse_sql=None),
    ]
