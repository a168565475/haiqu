from django.db import migrations, models
from django.db.models.functions import Floor


WEIGHT_ONLY_RETURN = models.Q(
    quantity=0, direction="OUT", source_type="PURCHASE_RETURN",
    snapshot__has_key="measurement_kind", snapshot__measurement_kind__isnull=False,
    snapshot__measurement_kind="HARDWARE_WEIGHT", weight_quantity__isnull=False, weight_quantity__gt=0,
)
WEIGHT_ONLY_INBOUND = models.Q(
    quantity=0, direction="IN", source_type="MATERIAL_INBOUND",
    snapshot__has_key="measurement_kind", snapshot__measurement_kind__isnull=False,
    snapshot__measurement_kind="HARDWARE_WEIGHT", weight_quantity__isnull=False, weight_quantity__gt=0,
)
CATALOG_STOCK = models.Q(stock_kind_snapshot__in=["CATALOG_RAW", "CATALOG_SEMI"])
PUBLIC_WEIGHT_ONLY_INBOUND = models.Q(
    quantity=0, direction="IN", source_type="MATERIAL_INBOUND", stock_kind_snapshot__in=["CATALOG_RAW", "CATALOG_SEMI"],
    snapshot__has_key="measurement_kind", snapshot__measurement_kind__isnull=False,
    snapshot__measurement_kind="HARDWARE_WEIGHT", weight_quantity__isnull=False, weight_quantity__gt=0,
)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0035_packaging_purchase_receiving_section")]

    operations = [
        migrations.RemoveConstraint(model_name="materialstockmovement", name="inv_mat_movement_qty_positive"),
        migrations.AddConstraint(
            model_name="materialstockmovement",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gt=0) | WEIGHT_ONLY_INBOUND | WEIGHT_ONLY_RETURN,
                name="inv_mat_movement_qty_positive",
            ),
        ),
        migrations.RemoveConstraint(model_name="publicstockmovement", name="inv_pub_movement_whole_qty"),
        migrations.AddConstraint(
            model_name="publicstockmovement",
            constraint=models.CheckConstraint(
                condition=(models.Q(quantity__gt=0) | PUBLIC_WEIGHT_ONLY_INBOUND | WEIGHT_ONLY_RETURN)
                & models.Q(before_quantity__gte=0) & models.Q(after_quantity__gte=0)
                & (CATALOG_STOCK | (models.Q(quantity=Floor(models.F("quantity")))
                    & models.Q(before_quantity=Floor(models.F("before_quantity")))
                    & models.Q(after_quantity=Floor(models.F("after_quantity"))))),
                name="inv_pub_movement_whole_qty",
            ),
        ),
    ]
