import uuid

import django.db.models.deletion
from django.db import migrations, models


def backfill_workflow_records(apps, schema_editor):
    SampleRequest = apps.get_model("samples", "SampleRequest")
    SampleWorkflowRecord = apps.get_model("samples", "SampleWorkflowRecord")
    records = []
    for sample in SampleRequest.objects.all().iterator(chunk_size=500):
        records.append(
            SampleWorkflowRecord(
                id=uuid.uuid4(),
                sample_request_id=sample.pk,
                stage="REQUEST_CREATED",
                operated_by_employee_id=sample.requested_by_employee_id,
                operated_at=sample.created_at,
                note="历史样品需求记录回填。",
            )
        )
        if sample.manual_request_number or sample.created_by_employee_id:
            records.append(
                SampleWorkflowRecord(
                    id=uuid.uuid4(),
                    sample_request_id=sample.pk,
                    stage="REQUIREMENTS_COMPLETED",
                    operated_by_employee_id=sample.created_by_employee_id,
                    operated_at=max(sample.created_at, sample.updated_at),
                    note="历史工厂完善记录回填。",
                )
            )
        if len(records) >= 1000:
            SampleWorkflowRecord.objects.bulk_create(records, ignore_conflicts=True)
            records = []
    if records:
        SampleWorkflowRecord.objects.bulk_create(records, ignore_conflicts=True)


def clear_workflow_records(apps, schema_editor):
    SampleWorkflowRecord = apps.get_model("samples", "SampleWorkflowRecord")
    SampleWorkflowRecord.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0001_initial"),
        ("organizations", "0002_seed_root_organization"),
        ("samples", "0012_sam09_two_stage_sample_request"),
    ]

    operations = [
        migrations.AlterField(
            model_name="samplerequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "草稿"),
                    ("PENDING_COMPLETION", "待工厂完善"),
                    ("PENDING", "财务待确认"),
                    ("PMC_REVIEW", "PMC待审核"),
                    ("METALWORK_PENDING", "待上传金工参数"),
                    ("CUTTING_PENDING", "待上传裁剪参数"),
                    ("FINISHED", "流程已结束"),
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
                        "PMC_REVIEW",
                        "METALWORK_PENDING",
                        "CUTTING_PENDING",
                        "FINISHED",
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
                        "PMC_REVIEW",
                        "METALWORK_PENDING",
                        "CUTTING_PENDING",
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
        migrations.CreateModel(
            name="SampleWorkflowRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("REQUEST_CREATED", "创建样品需求"),
                            ("REQUIREMENTS_COMPLETED", "工厂完善并提交"),
                            ("FINANCE_CONFIRMED", "财务确认完成"),
                            ("PMC_APPROVED", "PMC审核通过"),
                            ("METALWORK_PARAMETERS", "金工参数上传"),
                            ("CUTTING_PARAMETERS", "裁剪参数上传"),
                            ("WORKFLOW_FINISHED", "样品单流程结束"),
                        ],
                        max_length=40,
                    ),
                ),
                ("note", models.TextField(blank=True)),
                ("operated_at", models.DateTimeField()),
                (
                    "business_file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_workflow_records",
                        to="files.businessfile",
                    ),
                ),
                (
                    "operated_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sample_workflow_operations",
                        to="organizations.employee",
                    ),
                ),
                (
                    "sample_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workflow_records",
                        to="samples.samplerequest",
                    ),
                ),
            ],
            options={
                "db_table": "sample_workflow_record",
                "ordering": ["operated_at", "created_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleworkflowrecord",
            constraint=models.UniqueConstraint(
                fields=("sample_request", "stage"),
                name="sample_workflow_stage_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleworkflowrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    stage__in=[
                        "REQUEST_CREATED",
                        "REQUIREMENTS_COMPLETED",
                        "FINANCE_CONFIRMED",
                        "PMC_APPROVED",
                        "METALWORK_PARAMETERS",
                        "CUTTING_PARAMETERS",
                        "WORKFLOW_FINISHED",
                    ]
                ),
                name="sample_workflow_stage_valid",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleworkflowrecord",
            index=models.Index(
                fields=["sample_request", "operated_at", "id"],
                name="sample_workflow_timeline_idx",
            ),
        ),
        migrations.RunPython(backfill_workflow_records, clear_workflow_records),
    ]
