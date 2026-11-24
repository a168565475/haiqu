from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.db.models.functions import Floor


class Migration(migrations.Migration):
    dependencies = [("inventory", "0030_material_transfer_weight")]

    operations = [
        migrations.AlterField(
            model_name="materialinboundline", name="received_quantity",
            field=models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]),
        ),
        migrations.AlterField(
            model_name="materialstockmovement", name="quantity",
            field=models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]),
        ),
        migrations.RemoveConstraint(model_name="materialinboundline", name="inv_material_inbound_qty_positive"),
        migrations.AddConstraint(
            model_name="materialinboundline",
            constraint=models.CheckConstraint(
                condition=models.Q(received_quantity__gt=0) | models.Q(received_quantity=0, measurement_kind="OTHER",
                    calculation_snapshot__has_key="measurement_kind", calculation_snapshot__measurement_kind__isnull=False,
                    calculation_snapshot__measurement_kind="HARDWARE_WEIGHT",
                    received_weight_kg__isnull=False, received_weight_kg__gt=0),
                name="inv_material_inbound_qty_positive",
            ),
        ),
        migrations.RemoveConstraint(model_name="materialstockmovement", name="inv_mat_movement_qty_positive"),
        migrations.AddConstraint(
            model_name="materialstockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gt=0) | models.Q(quantity=0, direction="IN", source_type="MATERIAL_INBOUND",
                    snapshot__has_key="measurement_kind", snapshot__measurement_kind__isnull=False, snapshot__measurement_kind="HARDWARE_WEIGHT",
                    weight_quantity__isnull=False, weight_quantity__gt=0),
                name="inv_mat_movement_qty_positive",
            ),
        ),
        migrations.RemoveConstraint(model_name="publicstockmovement", name="inv_pub_movement_whole_qty"),
        migrations.AddConstraint(
            model_name="publicstockmovement",
            constraint=models.CheckConstraint(
                condition=(models.Q(quantity__gt=0) | models.Q(quantity=0, direction="IN", source_type="MATERIAL_INBOUND",
                    stock_kind_snapshot__in=["CATALOG_RAW", "CATALOG_SEMI"],
                    snapshot__has_key="measurement_kind", snapshot__measurement_kind__isnull=False,
                    snapshot__measurement_kind="HARDWARE_WEIGHT",
                    weight_quantity__isnull=False, weight_quantity__gt=0))
                    & models.Q(before_quantity__gte=0) & models.Q(after_quantity__gte=0)
                    & (models.Q(stock_kind_snapshot__in=["CATALOG_RAW", "CATALOG_SEMI"])
                       | (models.Q(quantity=Floor(models.F("quantity"))) & models.Q(before_quantity=Floor(models.F("before_quantity")))
                          & models.Q(after_quantity=Floor(models.F("after_quantity"))))),
                name="inv_pub_movement_whole_qty",
            ),
        ),
    ]
