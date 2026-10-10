import uuid

import apps.core.models
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0015_sample_inventory"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleInventoryOutbound",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "outbound_number",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        validators=[apps.core.models.uppercase_code_validator],
                    ),
                ),
                ("operated_at", models.DateTimeField()),
                (
                    "operated_by_employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_inventory_outbounds",
                        to="organizations.employee",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_outbound",
                "ordering": ["-operated_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="SampleInventoryOutboundLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("outbound_quantity", models.PositiveIntegerField()),
                (
                    "outbound_method",
                    models.CharField(
                        choices=[
                            ("MERCHANDISER_MAIL", "跟单员邮寄"),
                            ("SALESPERSON_CARRY", "业务员带走"),
                            ("OTHER", "其他"),
                        ],
                        max_length=30,
                    ),
                ),
                ("courier_company", models.CharField(blank=True, max_length=150)),
                ("tracking_number", models.CharField(blank=True, max_length=150)),
                ("remark", models.CharField(blank=True, max_length=500)),
                (
                    "inventory_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="outbound_lines",
                        to="samples.sampleinventoryline",
                    ),
                ),
                (
                    "outbound",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lines",
                        to="samples.sampleinventoryoutbound",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_outbound_line",
                "ordering": ["-outbound__operated_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryoutbound",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("outbound_number", django.db.models.functions.text.Upper(models.F("outbound_number")))
                ),
                name="sample_outbound_number_upper",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryoutbound",
            index=models.Index(fields=["-operated_at", "-id"], name="sample_outbound_time_idx"),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryoutboundline",
            constraint=models.UniqueConstraint(
                fields=("outbound", "inventory_line"),
                name="sample_outbound_inventory_line_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryoutboundline",
            constraint=models.CheckConstraint(
                condition=models.Q(("outbound_quantity__gt", 0)),
                name="sample_outbound_quantity_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryoutboundline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("outbound_method__in", ["MERCHANDISER_MAIL", "SALESPERSON_CARRY", "OTHER"])
                ),
                name="sample_outbound_method_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryoutboundline",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("outbound_method", "MERCHANDISER_MAIL"))
                    & ~models.Q(("courier_company", ""))
                    & ~models.Q(("tracking_number", ""))
                )
                | models.Q(("outbound_method", "SALESPERSON_CARRY"))
                | (models.Q(("outbound_method", "OTHER")) & ~models.Q(("remark", ""))),
                name="sample_outbound_method_fields",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryoutboundline",
            index=models.Index(fields=["outbound_method", "id"], name="sample_outbound_method_idx"),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryoutboundline",
            index=models.Index(fields=["inventory_line", "id"], name="sample_outbound_inventory_idx"),
        ),
    ]
