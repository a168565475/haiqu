import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

import apps.procurement.tracking_models


def seed_tracking_policy(apps, schema_editor):
    policy = apps.get_model("procurement", "PurchaseTrackingPolicy")
    policy.objects.using(schema_editor.connection.alias).get_or_create(
        key="default",
        defaults={"bom_timeout_days": 2, "category_lead_days": {
            "TUBE": 2, "FABRIC": 2, "HARDWARE": 2, "PLASTIC": 2,
            "PACKAGING": 2, "AUXILIARY": 2, "FABRIC_SEMI": 2,
        }},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0004_employee_workshop_employee_workshop_is_supervisor_and_more"),
        ("procurement", "0029_tracking_content_immutable"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseTrackingPolicy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("key", models.CharField(default="default", editable=False, max_length=16, unique=True)),
                ("bom_timeout_days", models.PositiveSmallIntegerField(blank=True, default=2, null=True, validators=[django.core.validators.MaxValueValidator(365)])),
                ("category_lead_days", models.JSONField(default=apps.procurement.tracking_models.default_tracking_category_lead_days, validators=[apps.procurement.tracking_models.validate_tracking_category_lead_days])),
                ("updated_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="organizations.employee")),
            ],
            options={
                "db_table": "procurement_tracking_policy",
                "default_permissions": (),
                "constraints": [
                    models.CheckConstraint(condition=models.Q(key="default"), name="tracking_policy_singleton_key"),
                    models.CheckConstraint(condition=models.Q(bom_timeout_days__isnull=True) | models.Q(bom_timeout_days__gte=0, bom_timeout_days__lte=365), name="tracking_policy_bom_days_range"),
                ],
            },
        ),
        migrations.RunPython(seed_tracking_policy, migrations.RunPython.noop),
    ]
