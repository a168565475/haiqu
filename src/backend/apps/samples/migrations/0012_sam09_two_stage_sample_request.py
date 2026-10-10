import django.db.models.deletion
from django.db import migrations, models


def backfill_requested_by(apps, schema_editor):
    SampleRequest = apps.get_model("samples", "SampleRequest")
    SampleRequest.objects.filter(
        requested_by_employee__isnull=True,
        created_by_employee__isnull=False,
    ).update(requested_by_employee_id=models.F("created_by_employee_id"))


def clear_requested_by(apps, schema_editor):
    SampleRequest = apps.get_model("samples", "SampleRequest")
    SampleRequest.objects.update(requested_by_employee_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("samples", "0011_sam08_independent_form"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_sample_intake_number_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_sample_intake_number_seq;",
        ),
        migrations.AddField(
            model_name="samplerequest",
            name="intake_number",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="samplerequest",
            name="requested_by_employee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="requested_sample_requests",
                to="organizations.employee",
            ),
        ),
        migrations.RunPython(backfill_requested_by, clear_requested_by),
        migrations.AlterField(
            model_name="samplerequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "草稿"),
                    ("PENDING_COMPLETION", "待工厂完善"),
                    ("PENDING", "费用待处理"),
                    ("PREPARING", "待寄出"),
                    ("SHIPPED", "运输中"),
                    ("DELIVERED", "已签收"),
                    ("FEEDBACK_PENDING", "待反馈"),
                    ("CONFIRMED", "已确认"),
                    ("COMPLETED", "已确认（历史）"),
                    ("REJECTED", "未通过"),
                    ("CANCELLED", "已取消"),
                ],
                default="DRAFT",
                max_length=30,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="samplerequest",
            name="sample_request_status_valid",
        ),
        migrations.AddConstraint(
            model_name="samplerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "DRAFT",
                        "PENDING_COMPLETION",
                        "PENDING",
                        "PREPARING",
                        "SHIPPED",
                        "DELIVERED",
                        "FEEDBACK_PENDING",
                        "CONFIRMED",
                        "COMPLETED",
                        "REJECTED",
                        "CANCELLED",
                    ]
                ),
                name="sample_request_status_valid",
            ),
        ),
        migrations.RemoveIndex(
            model_name="samplerequest",
            name="sample_processing_queue_idx",
        ),
        migrations.AddIndex(
            model_name="samplerequest",
            index=models.Index(
                condition=models.Q(
                    archived_at__isnull=True,
                    status__in=[
                        "PENDING_COMPLETION",
                        "PENDING",
                        "PREPARING",
                        "SHIPPED",
                        "DELIVERED",
                        "FEEDBACK_PENDING",
                    ],
                ),
                fields=["status", "requested_at", "id"],
                name="sample_processing_queue_idx",
            ),
        ),
        migrations.AlterModelOptions(
            name="samplerequest",
            options={
                "permissions": [
                    ("decide_sample_fee", "可决定样品费用"),
                    ("ship_sample", "可寄送样品"),
                    ("view_all_samplerequest", "可查看全部样品流程"),
                    ("complete_sample_requirements", "可完善样品需求"),
                ]
            },
        ),
    ]
