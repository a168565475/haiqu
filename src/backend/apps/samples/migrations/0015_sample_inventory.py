import uuid

import apps.core.models
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("samples", "0014_sam11_product_sampling_details"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleInventoryReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "receipt_number",
                    models.CharField(
                        max_length=50,
                        unique=True,
                        validators=[apps.core.models.uppercase_code_validator],
                    ),
                ),
                ("submitted_at", models.DateTimeField()),
                (
                    "submitted_by_employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="submitted_sample_inventory_receipts",
                        to="organizations.employee",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_receipt",
                "ordering": ["-submitted_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="SampleInventoryLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category_name_snapshot", models.CharField(blank=True, max_length=150)),
                ("product_name_snapshot", models.CharField(max_length=500)),
                ("specification_snapshot", models.TextField(blank=True)),
                ("color_name_snapshot", models.CharField(blank=True, max_length=200)),
                ("sampling_quantity", models.PositiveIntegerField()),
                ("received_quantity", models.PositiveIntegerField()),
                ("outbound_quantity", models.PositiveIntegerField(default=0)),
                ("loaned_quantity", models.PositiveIntegerField(default=0)),
                ("location", models.CharField(default="样品库", max_length=150)),
                (
                    "receipt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lines",
                        to="samples.sampleinventoryreceipt",
                    ),
                ),
                (
                    "sample_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_lines",
                        to="samples.sampleitem",
                    ),
                ),
            ],
            options={
                "db_table": "sample_inventory_line",
                "ordering": ["-receipt__submitted_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("receipt_number", django.db.models.functions.text.Upper(models.F("receipt_number")))
                ),
                name="sample_inventory_receipt_no_upper",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryreceipt",
            index=models.Index(fields=["-submitted_at", "-id"], name="sample_inv_receipt_time_idx"),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryline",
            constraint=models.UniqueConstraint(
                fields=("receipt", "sample_item"),
                name="sample_inventory_receipt_item_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryline",
            constraint=models.CheckConstraint(
                condition=models.Q(("sampling_quantity__gt", 0)),
                name="sample_inventory_sampling_qty_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryline",
            constraint=models.CheckConstraint(
                condition=models.Q(("received_quantity__gt", 0)),
                name="sample_inventory_received_qty_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryline",
            constraint=models.CheckConstraint(
                condition=models.Q(("received_quantity__lte", models.F("sampling_quantity"))),
                name="sample_inventory_received_lte_sampled",
            ),
        ),
        migrations.AddConstraint(
            model_name="sampleinventoryline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "received_quantity__gte",
                        models.F("outbound_quantity") + models.F("loaned_quantity"),
                    )
                ),
                name="sample_inventory_available_nonneg",
            ),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryline",
            index=models.Index(fields=["location", "id"], name="sample_inventory_location_idx"),
        ),
        migrations.AddIndex(
            model_name="sampleinventoryline",
            index=models.Index(fields=["sample_item", "id"], name="sample_inventory_item_idx"),
        ),
    ]
