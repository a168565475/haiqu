import uuid
from decimal import Decimal

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0027_catalog_pipe_stock_bridge"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS haiqu_material_transfer_seq START WITH 1;",
            reverse_sql="DROP SEQUENCE IF EXISTS haiqu_material_transfer_seq;",
        ),
        migrations.CreateModel(
            name="MaterialTransfer",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("transfer_number", models.CharField(max_length=50, unique=True, validators=[django.core.validators.RegexValidator(regex="^[A-Z0-9][A-Z0-9._-]*$", message="编码只能包含大写字母、数字、点、下划线和连字符。") ])),
                ("client_request_id", models.UUIDField(unique=True, editable=False)),
                ("request_snapshot", models.JSONField(default=dict, editable=False)),
                ("direction", models.CharField(choices=[("IN", "一般入库"), ("OUT", "一般出库")], max_length=10)),
                ("transfer_date", models.DateField(default=django.utils.timezone.localdate)),
                ("remark", models.TextField()),
                ("operated_by_employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_transfers", to="organizations.employee")),
            ],
            options={
                "db_table": "inventory_material_transfer",
                "ordering": ["-transfer_date", "-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["direction", "-transfer_date"], name="inv_transfer_dir_date_idx"),
                    models.Index(fields=["operated_by_employee", "-created_at"], name="inv_transfer_actor_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(condition=Q(direction__in=["IN", "OUT"]), name="inv_transfer_direction_valid"),
                    models.CheckConstraint(condition=~Q(remark=""), name="inv_transfer_remark_required"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MaterialTransferLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("line_key", models.UUIDField(default=uuid.uuid4, editable=False)),
                ("material_selection_snapshot", models.JSONField()),
                ("quantity", models.DecimalField(decimal_places=4, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))])),
                ("raw_bar_length_m", models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)),
                ("material_catalog", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_transfer_lines", to="material_catalog.materialcatalog")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventory.materialtransfer")),
                ("zone", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_transfer_lines", to="inventory.warehousezone")),
            ],
            options={
                "db_table": "inventory_material_transfer_line",
                "ordering": ["transfer", "id"],
                "indexes": [models.Index(fields=["material_catalog", "zone"], name="inv_transfer_catalog_zone_idx")],
                "constraints": [
                    models.UniqueConstraint(fields=["transfer", "line_key"], name="inv_transfer_line_key_uniq"),
                    models.CheckConstraint(condition=Q(quantity__gt=0), name="inv_transfer_line_qty_positive"),
                    models.CheckConstraint(condition=Q(raw_bar_length_m__isnull=True) | Q(raw_bar_length_m__gt=0), name="inv_transfer_line_pipe_length_positive"),
                ],
            },
        ),
    ]
