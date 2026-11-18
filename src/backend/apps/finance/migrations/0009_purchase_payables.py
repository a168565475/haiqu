import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0008_partial_deposit_allocations"),
        ("inventory", "0030_material_transfer_weight"),
        ("procurement", "0031_pipe_weight_purchase"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchasePayable",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("number", models.CharField(max_length=50, unique=True)),
                ("supplier_number_snapshot", models.CharField(blank=True, max_length=8)),
                ("supplier_name_snapshot", models.CharField(blank=True, max_length=255)),
                ("purchase_order_number_snapshot", models.CharField(blank=True, max_length=50)),
                ("inbound_number_snapshot", models.CharField(blank=True, max_length=50)),
                ("currency_code_snapshot", models.CharField(blank=True, max_length=3)),
                ("currency_name_snapshot", models.CharField(blank=True, max_length=150)),
                ("status", models.CharField(choices=[("WAITING_PRICE", "待核价"), ("WAITING_FINANCE_CONFIRM", "待财务确认"), ("WAITING_PAYMENT", "待付款"), ("VOID", "已作废")], default="WAITING_PRICE", max_length=40)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=22, null=True)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.CharField(blank=True, max_length=500)),
                ("confirmed_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_purchase_payables", to="organizations.employee")),
                ("material_inbound", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_payables", to="inventory.materialinbound")),
                ("supplier", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_payables", to="procurement.supplier")),
                ("voided_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="voided_purchase_payables", to="organizations.employee")),
            ],
            options={
                "db_table": "finance_purchase_payable",
                "ordering": ["-created_at", "-id"],
                "default_permissions": ("add", "change", "delete", "view"),
                "permissions": [("confirm_purchasepayable", "确认采购应付"), ("void_purchasepayable", "作废采购应付")],
            },
        ),
        migrations.CreateModel(
            name="PurchasePayableLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("material_snapshot", models.CharField(blank=True, max_length=200)),
                ("specification_snapshot", models.CharField(blank=True, max_length=500)),
                ("part_name_snapshot", models.CharField(blank=True, max_length=300)),
                ("material_attributes_snapshot", models.JSONField(blank=True, default=dict)),
                ("source_unit_text_snapshot", models.CharField(blank=True, max_length=50)),
                ("accepted_quantity", models.DecimalField(decimal_places=4, max_digits=18, validators=[django.core.validators.MinValueValidator(0)])),
                ("accepted_weight_kg", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("accepted_bar_count", models.PositiveBigIntegerField(blank=True, null=True)),
                ("reference_unit_price", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("reference_amount", models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("unit_price", models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("price_unit_text", models.CharField(blank=True, max_length=50)),
                ("currency_code_snapshot", models.CharField(blank=True, max_length=3)),
                ("price_source", models.CharField(blank=True, max_length=100)),
                ("price_confirmed_by_name", models.CharField(blank=True, max_length=150)),
                ("price_confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("price_remark", models.TextField(blank=True)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=22, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("material_inbound_line", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_payable_line", to="inventory.materialinboundline")),
                ("payable", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="finance.purchasepayable")),
                ("purchase_order_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_payable_lines", to="procurement.purchaseorderline")),
            ],
            options={
                "db_table": "finance_purchase_payable_line",
                "ordering": ["id"],
            },
        ),
        migrations.AddIndex(model_name="purchasepayable", index=models.Index(fields=["status", "-created_at"], name="finance_payable_status_idx")),
        migrations.AddIndex(model_name="purchasepayable", index=models.Index(fields=["supplier", "-created_at"], name="finance_payable_supplier_idx")),
        migrations.AddIndex(model_name="purchasepayable", index=models.Index(fields=["material_inbound", "-created_at"], name="finance_payable_inbound_idx")),
        migrations.AddIndex(model_name="purchasepayableline", index=models.Index(fields=["payable", "id"], name="fin_pay_line_pay_idx")),
        migrations.AddIndex(model_name="purchasepayableline", index=models.Index(fields=["purchase_order_line", "id"], name="fin_pay_line_po_idx")),
        migrations.AddConstraint(model_name="purchasepayable", constraint=models.CheckConstraint(condition=Q(status__in=["WAITING_PRICE", "WAITING_FINANCE_CONFIRM", "WAITING_PAYMENT", "VOID"]), name="finance_payable_status_valid")),
        migrations.AddConstraint(model_name="purchasepayable", constraint=models.UniqueConstraint(fields=["material_inbound", "supplier"], name="finance_payable_inbound_supplier_unique")),
        migrations.AddConstraint(model_name="purchasepayable", constraint=models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0), name="finance_payable_amount_nonnegative")),
        migrations.AddConstraint(model_name="purchasepayable", constraint=models.CheckConstraint(condition=Q(status__in=["WAITING_PAYMENT", "VOID"]) | Q(confirmed_at__isnull=True), name="finance_payable_confirmed_at_state_valid")),
        migrations.AddConstraint(model_name="purchasepayable", constraint=models.CheckConstraint(condition=Q(status="VOID", voided_at__isnull=False, voided_by_employee__isnull=False) | (~Q(status="VOID") & Q(voided_at__isnull=True) & Q(voided_by_employee__isnull=True)), name="finance_payable_void_state_valid")),
        migrations.AddConstraint(model_name="purchasepayableline", constraint=models.CheckConstraint(condition=Q(accepted_quantity__gte=0), name="finance_payable_line_qty_nonnegative")),
        migrations.AddConstraint(model_name="purchasepayableline", constraint=models.CheckConstraint(condition=Q(accepted_weight_kg__isnull=True) | Q(accepted_weight_kg__gte=0), name="finance_payable_line_weight_nonnegative")),
        migrations.AddConstraint(model_name="purchasepayableline", constraint=models.CheckConstraint(condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0), name="finance_payable_line_price_nonnegative")),
        migrations.AddConstraint(model_name="purchasepayableline", constraint=models.CheckConstraint(condition=Q(amount__isnull=True) | Q(amount__gte=0), name="finance_payable_line_amount_nonnegative")),
    ]
