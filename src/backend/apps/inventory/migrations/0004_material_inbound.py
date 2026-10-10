import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import uuid
from decimal import Decimal

from django.db import migrations, models


def backfill_finished_goods_pinyin(apps, schema_editor):
    from apps.reference_data.pinyin_search import build_pinyin_search

    receipt_model = apps.get_model("inventory", "FinishedGoodsReceipt")
    for receipt in receipt_model.objects.all().iterator(chunk_size=500):
        receipt.product_name_pinyin_search = build_pinyin_search(receipt.product_name_snapshot)
        receipt.save(update_fields=["product_name_pinyin_search"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_optional_receipt_packaging"),
        ("organizations", "0002_seed_root_organization"),
        ("procurement", "0004_alter_purchaseorder_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="finishedgoodsreceipt",
            name="product_name_pinyin_search",
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(backfill_finished_goods_pinyin, migrations.RunPython.noop),
        migrations.CreateModel(
            name="MaterialInbound",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("inbound_number", models.CharField(max_length=50, unique=True, validators=[django.core.validators.RegexValidator(message="编码只能包含大写字母、数字、点、下划线和连字符。", regex="^[A-Z0-9][A-Z0-9._-]*$")])),
                ("inbound_date", models.DateField(default=django.utils.timezone.localdate)),
                ("remark", models.TextField(blank=True)),
                ("received_by_employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_inbounds", to="organizations.employee")),
            ],
            options={
                "db_table": "inventory_material_inbound",
                "ordering": ["-inbound_date", "-created_at", "-id"],
                "permissions": [("receive_material", "Can receive material inventory")],
            },
        ),
        migrations.CreateModel(
            name="MaterialInboundLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("received_quantity", models.DecimalField(decimal_places=4, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))])),
                ("remark", models.TextField(blank=True)),
                ("purchase_order_number_snapshot", models.CharField(max_length=50)),
                ("production_task_number_snapshot", models.CharField(max_length=50)),
                ("sales_order_number_snapshot", models.CharField(blank=True, max_length=100)),
                ("supplier_number_snapshot", models.CharField(blank=True, max_length=8)),
                ("supplier_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("bom_number_snapshot", models.CharField(max_length=80)),
                ("product_name_snapshot", models.CharField(max_length=200)),
                ("section_type_snapshot", models.CharField(max_length=20)),
                ("section_title_snapshot", models.CharField(max_length=300)),
                ("category_snapshot", models.CharField(blank=True, max_length=150)),
                ("material_snapshot", models.CharField(blank=True, max_length=200)),
                ("part_name_snapshot", models.CharField(max_length=300)),
                ("specification_snapshot", models.CharField(blank=True, max_length=500)),
                ("raw_material_snapshot", models.TextField(blank=True)),
                ("source_unit_text_snapshot", models.CharField(max_length=50)),
                ("purchased_quantity_snapshot", models.DecimalField(decimal_places=4, max_digits=18)),
                ("material_pinyin_search", models.TextField(blank=True)),
                ("inbound", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.materialinbound")),
                ("location", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_inbound_lines", to="inventory.warehouselocation")),
                ("purchase_order_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_inbound_lines", to="procurement.purchaseorderline")),
            ],
            options={
                "db_table": "inventory_material_inbound_line",
                "ordering": ["inbound", "id"],
                "indexes": [
                    models.Index(fields=["purchase_order_line", "created_at"], name="inv_mat_po_line_idx"),
                    models.Index(fields=["location", "created_at"], name="inv_mat_location_idx"),
                    models.Index(fields=["section_title_snapshot"], name="inv_mat_section_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("received_quantity__gt", 0)), name="inv_material_inbound_qty_positive"),
                    models.CheckConstraint(condition=models.Q(("purchased_quantity_snapshot__gt", 0)), name="inv_material_purchase_qty_positive"),
                ],
            },
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_material_inbound_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_material_inbound_seq;",
        ),
    ]
