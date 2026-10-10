import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("quotations", "0011_container_tier_price_and_seller_export_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuotationEmailDispatchAttempt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("idempotency_key", models.UUIDField()),
                ("payload_hash", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PROCESSING", "发送处理中"),
                            ("ACCEPTED", "邮件服务已接受"),
                            ("FAILED", "确认未发送"),
                            ("UNCERTAIN", "结果待核对"),
                        ],
                        default="PROCESSING",
                        max_length=20,
                    ),
                ),
                ("recipient", models.EmailField(max_length=254)),
                ("cc_snapshot", models.JSONField(blank=True, default=list)),
                ("subject", models.CharField(max_length=250)),
                ("body_html", models.TextField()),
                ("recipient_snapshot", models.JSONField(default=dict)),
                ("attachment_snapshot", models.JSONField(default=dict)),
                ("follow_up_due_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_note", models.TextField(blank=True)),
                (
                    "dispatch_record",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="email_attempt",
                        to="quotations.quotationdispatchrecord",
                    ),
                ),
                (
                    "price_basis",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="email_dispatch_attempts",
                        to="quotations.quotationpricebasis",
                    ),
                ),
                (
                    "quotation_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="email_dispatch_attempts",
                        to="quotations.quotationdocument",
                    ),
                ),
                (
                    "quotation_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="email_dispatch_attempts",
                        to="quotations.quotationversion",
                    ),
                ),
                (
                    "requested_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="quotation_email_dispatch_attempts",
                        to="organizations.employee",
                    ),
                ),
                (
                    "resolved_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_quotation_email_dispatch_attempts",
                        to="organizations.employee",
                    ),
                ),
            ],
            options={"db_table": "quotation_email_dispatch_attempt"},
        ),
        migrations.AddConstraint(
            model_name="quotationemaildispatchattempt",
            constraint=models.CheckConstraint(
                condition=Q(status__in=["PROCESSING", "ACCEPTED", "FAILED", "UNCERTAIN"]),
                name="quote_email_attempt_status_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotationemaildispatchattempt",
            constraint=models.UniqueConstraint(
                fields=("quotation_version", "idempotency_key"),
                name="quote_email_attempt_idem_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="quotationemaildispatchattempt",
            index=models.Index(
                fields=["quotation_version", "-created_at", "-id"],
                name="q_email_attempt_hist_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="quotationemaildispatchattempt",
            index=models.Index(
                condition=Q(status__in=["PROCESSING", "UNCERTAIN"]),
                fields=["status", "updated_at", "id"],
                name="q_email_attempt_open_idx",
            ),
        ),
    ]
