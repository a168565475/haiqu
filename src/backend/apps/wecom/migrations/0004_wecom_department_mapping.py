import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_role_department"),
        ("wecom", "0003_notificationevent_notificationrecipient_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeComDepartmentMapping",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("corp_id", models.CharField(max_length=100)),
                ("wecom_department_id", models.PositiveBigIntegerField()),
                ("wecom_department_name", models.CharField(max_length=768)),
                ("organization_unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                       related_name="wecom_department_mappings", to="organizations.organizationunit")),
            ],
            options={
                "db_table": "wecom_department_mapping",
                "ordering": ["wecom_department_id"],
                "constraints": [
                    models.UniqueConstraint(fields=("corp_id", "wecom_department_id"), name="wecom_department_source_unique"),
                    models.CheckConstraint(condition=models.Q(wecom_department_id__gte=1, wecom_department_id__lt=4294967296),
                                           name="wecom_department_uint32"),
                ],
            },
        ),
    ]
