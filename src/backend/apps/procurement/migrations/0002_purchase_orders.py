import uuid
from decimal import Decimal

import django.contrib.postgres.fields
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


NUMBER_RULE_ID = uuid.UUID("26e8fdd3-e419-4e57-ad87-dd34e6685e09")


def seed_purchase_order_number_rule(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.update_or_create(
        number_type="PURCHASE_ORDER",
        defaults={
            "id": NUMBER_RULE_ID,
            "chinese_name": "采购订单号",
            "prefix": "CG",
            "format_pattern": "{prefix}-{date}-{sequence}",
            "sequence_name": "haiqu_purchase_order_number_seq",
            "sequence_padding": 6,
            "date_granularity": "MONTH",
            "reset_policy": "NEVER",
            "is_configured": True,
            "sort_order": 62,
            "status": "ACTIVE",
            "description": "采购订单模块新建编号规则：CG-年月-六位全局流水；不是历史编号识别结果。",
        },
    )


def remove_purchase_order_number_rule(apps, schema_editor):
    NumberRule = apps.get_model("reference_data", "NumberRule")
    NumberRule.objects.filter(number_type="PURCHASE_ORDER", id=NUMBER_RULE_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0001_initial"),
        ("boms", "0001_initial"),
        ("production_tasks", "0007_productiontask_status_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("order_number", models.CharField(max_length=50, unique=True, validators=[django.core.validators.RegexValidator(message="采购订单号必须是 CG-年月-六位流水。", regex="^CG-[0-9]{6}-[0-9]{6}$")])),
                ("production_task_number_snapshot", models.CharField(max_length=50)),
                ("sales_order_number_snapshot", models.CharField(max_length=100)),
                ("customer_name_snapshot", models.CharField(max_length=255)),
                ("source_revision", models.CharField(max_length=64)),
                ("currency_code_snapshot", models.CharField(blank=True, max_length=3)),
                ("currency_name_snapshot", models.CharField(blank=True, max_length=150)),
                ("currency_symbol_snapshot", models.CharField(blank=True, max_length=20)),
                ("is_mailed", models.BooleanField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "草稿"), ("SUBMITTED", "已提交")], default="DRAFT", max_length=20)),
                ("total_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("created_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_purchase_orders", to="organizations.employee")),
                ("currency", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_orders", to="reference_data.currency")),
                ("production_task", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order", to="production_tasks.productiontask")),
            ],
            options={
                "db_table": "procurement_purchase_order",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["status", "-created_at"], name="purchase_order_status_idx"),
                    models.Index(fields=["currency", "-created_at"], name="purchase_order_currency_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("status__in", ["DRAFT", "SUBMITTED"])), name="purchase_order_status_valid"),
                    models.CheckConstraint(condition=models.Q(("total_amount__isnull", True), ("total_amount__gte", 0), _connector="OR"), name="purchase_order_total_nonnegative"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PurchaseOrderLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("line_number", models.PositiveIntegerField()),
                ("source_bom_line_id_snapshot", models.UUIDField()),
                ("product_line_id_snapshot", models.UUIDField()),
                ("bom_number_snapshot", models.CharField(max_length=80)),
                ("product_number_snapshot", models.CharField(max_length=100)),
                ("product_code_snapshot", models.CharField(blank=True, max_length=100)),
                ("product_name_snapshot", models.CharField(max_length=200)),
                ("product_specification_snapshot", models.CharField(blank=True, max_length=300)),
                ("section_type_snapshot", models.CharField(max_length=20)),
                ("section_title_snapshot", models.CharField(max_length=300)),
                ("category_snapshot", models.CharField(blank=True, max_length=150)),
                ("material_snapshot", models.CharField(blank=True, max_length=200)),
                ("part_name_snapshot", models.CharField(max_length=300)),
                ("specification_snapshot", models.CharField(blank=True, max_length=500)),
                ("raw_material_snapshot", models.TextField(blank=True)),
                ("required_quantity", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("source_quantity_field", models.CharField(blank=True, max_length=80)),
                ("source_quantity_text", models.CharField(blank=True, max_length=255)),
                ("source_unit_text", models.CharField(blank=True, max_length=50)),
                ("quantity_parse_status", models.CharField(choices=[("READY", "已识别"), ("MISSING", "未填写"), ("INVALID", "格式异常")], max_length=20)),
                ("supplier_number_snapshot", models.CharField(blank=True, max_length=8)),
                ("supplier_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("supplier_type_snapshot", models.CharField(blank=True, max_length=20)),
                ("supplier_categories_snapshot", django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=30), blank=True, default=list, size=None)),
                ("delivery_date", models.DateField(blank=True, null=True)),
                ("actual_purchase_quantity", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))])),
                ("unit_price", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("amount", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(Decimal("0"))])),
                ("bom", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_lines", to="boms.bom")),
                ("bom_line", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="purchase_order_lines", to="boms.bomline")),
                ("purchase_order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="procurement.purchaseorder")),
                ("supplier", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_order_lines", to="procurement.supplier")),
            ],
            options={
                "db_table": "procurement_purchase_order_line",
                "ordering": ["purchase_order", "line_number"],
                "indexes": [
                    models.Index(fields=["supplier", "delivery_date"], name="po_line_supp_date_idx"),
                    models.Index(fields=["bom", "line_number"], name="purchase_line_bom_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("purchase_order", "line_number"), name="purchase_order_line_number_unique"),
                    models.UniqueConstraint(fields=("purchase_order", "source_bom_line_id_snapshot"), name="purchase_order_bom_line_unique"),
                    models.CheckConstraint(condition=models.Q(("quantity_parse_status__in", ["READY", "MISSING", "INVALID"])), name="purchase_qty_parse_status_valid"),
                    models.CheckConstraint(condition=models.Q(("required_quantity__isnull", True), ("required_quantity__gte", 0), _connector="OR"), name="purchase_required_qty_nonnegative"),
                    models.CheckConstraint(condition=models.Q(("actual_purchase_quantity__isnull", True), ("actual_purchase_quantity__gt", 0), _connector="OR"), name="purchase_actual_qty_positive"),
                    models.CheckConstraint(condition=models.Q(("unit_price__isnull", True), ("unit_price__gte", 0), _connector="OR"), name="purchase_unit_price_nonnegative"),
                    models.CheckConstraint(condition=models.Q(("amount__isnull", True), ("amount__gte", 0), _connector="OR"), name="purchase_line_amount_nonnegative"),
                    models.CheckConstraint(condition=models.Q(models.Q(("actual_purchase_quantity__isnull", True), ("amount__isnull", True)), models.Q(("amount__isnull", True), ("unit_price__isnull", True)), models.Q(("actual_purchase_quantity__isnull", False), ("amount__isnull", False), ("unit_price__isnull", False)), _connector="OR"), name="purchase_line_amount_completeness"),
                ],
            },
        ),
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_purchase_order_number_seq START WITH 1 INCREMENT BY 1 MINVALUE 1 CACHE 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_purchase_order_number_seq;",
        ),
        migrations.RunPython(seed_purchase_order_number_rule, remove_purchase_order_number_rule),
    ]
