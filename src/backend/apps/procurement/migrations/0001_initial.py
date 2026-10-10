import uuid

import django.contrib.postgres.fields
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


NUMBER_RULE_ID = uuid.UUID("c1270669-5c46-4ca1-b2fc-2a0cb03689ee")


def seed_supplier_number_rule(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.update_or_create(
        number_type="SUPPLIER",
        defaults={
            "id": NUMBER_RULE_ID,
            "chinese_name": "供应商编号",
            "prefix": "GYS",
            "format_pattern": "{prefix}{sequence}",
            "sequence_name": "haiqu_supplier_number_seq",
            "sequence_padding": 5,
            "date_granularity": "NONE",
            "reset_policy": "NEVER",
            "is_configured": True,
            "sort_order": 55,
            "status": "ACTIVE",
            "description": "依据现有供应商资料登记：GYS 加 5 位流水，历史最大 GYS00265，流水从 266 开始。",
        },
    )


def remove_supplier_number_rule(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.filter(number_type="SUPPLIER", id=NUMBER_RULE_ID).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("reference_data", "0022_seed_raw_material_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("supplier_number", models.CharField(max_length=8, unique=True, validators=[django.core.validators.RegexValidator(message="供应商编号必须是 GYS 加 5 位数字。", regex="^GYS[0-9]{5}$")])),
                ("supplier_type", models.CharField(choices=[("MATERIAL", "材料供应商"), ("FINISHED", "成品供应商")], max_length=20)),
                ("supplier_categories", django.contrib.postgres.fields.ArrayField(base_field=models.CharField(choices=[("TUBE", "管材"), ("HARDWARE", "五金"), ("PLASTIC_PART", "塑料件"), ("PACKAGING", "包材"), ("FABRIC", "面料"), ("AUXILIARY", "辅料"), ("FINISHED_GOODS", "成品")], max_length=30), default=list, size=None)),
                ("supplier_name", models.CharField(max_length=255)),
                ("payment_cycle", models.CharField(blank=True, choices=[("MONTHLY", "月结")], max_length=20)),
                ("remark", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=100)),
                ("is_disabled", models.BooleanField(default=False)),
                ("submitted_by_name", models.CharField(blank=True, max_length=150)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("created_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_suppliers", to="organizations.employee")),
                ("submitted_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="submitted_suppliers", to="organizations.employee")),
                ("updated_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="updated_suppliers", to="organizations.employee")),
            ],
            options={
                "db_table": "procurement_supplier",
                "ordering": ["-supplier_number", "-id"],
                "indexes": [
                    models.Index(fields=["supplier_type", "is_disabled"], name="supplier_type_disabled_idx"),
                    models.Index(fields=["payment_cycle", "-updated_at"], name="supplier_payment_idx"),
                    models.Index(fields=["-updated_at", "-id"], name="supplier_updated_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("supplier_number__regex", "^GYS[0-9]{5}$")), name="supplier_number_format_valid"),
                    models.CheckConstraint(condition=models.Q(("supplier_type__in", ["MATERIAL", "FINISHED"])), name="supplier_type_valid"),
                    models.CheckConstraint(condition=models.Q(("payment_cycle", ""), ("payment_cycle__in", ["MONTHLY"]), _connector="OR"), name="supplier_payment_cycle_valid"),
                ],
            },
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_supplier_number_seq START WITH 266 INCREMENT BY 1 MINVALUE 1 CACHE 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_supplier_number_seq;",
        ),
        migrations.RunPython(seed_supplier_number_rule, remove_supplier_number_rule),
    ]
