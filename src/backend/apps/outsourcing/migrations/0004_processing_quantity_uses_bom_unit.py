from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def preserve_legacy_processing_units(apps, schema_editor):
    ProcessingItem = apps.get_model("outsourcing", "OutsourcingProcessingItem")
    items = list(
        ProcessingItem.objects.using(schema_editor.connection.alias)
        .select_related("order_product__schedule_product__unit")
        .all()
    )
    for item in items:
        legacy_unit = item.order_product.schedule_product.unit
        item.unit_id = legacy_unit.pk
        item.unit_snapshot = legacy_unit.unit_name
    if items:
        ProcessingItem.objects.using(schema_editor.connection.alias).bulk_update(
            items,
            ["unit", "unit_snapshot"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("outsourcing", "0003_outsourcingdispatch_dispatch_date_and_more"),
        ("reference_data", "0028_fill_supplemental_accessory_units"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="outsourcingfactoryallocation",
            name="outs_allocation_qty_positive",
        ),
        migrations.RemoveConstraint(
            model_name="outsourcingprocessingitem",
            name="outs_processing_qty_positive",
        ),
        migrations.RemoveConstraint(
            model_name="outsourcingreturnline",
            name="outs_return_line_qty_positive",
        ),
        migrations.RenameField(
            model_name="outsourcingprocessingitem",
            old_name="quantity_sets",
            new_name="quantity",
        ),
        migrations.AlterField(
            model_name="outsourcingprocessingitem",
            name="quantity",
            field=models.DecimalField(
                decimal_places=4,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))],
            ),
        ),
        migrations.AddField(
            model_name="outsourcingprocessingitem",
            name="unit",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="outsourcing_processing_items",
                to="reference_data.productionunit",
            ),
        ),
        migrations.AddField(
            model_name="outsourcingprocessingitem",
            name="unit_snapshot",
            field=models.CharField(blank=True, default="", max_length=50),
            preserve_default=False,
        ),
        migrations.RunPython(
            preserve_legacy_processing_units,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="outsourcingprocessingitem",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="outsourcing_processing_items",
                to="reference_data.productionunit",
            ),
        ),
        migrations.AlterField(
            model_name="outsourcingprocessingitem",
            name="unit_snapshot",
            field=models.CharField(max_length=50),
        ),
        migrations.RenameField(
            model_name="outsourcingfactoryallocation",
            old_name="allocated_quantity_sets",
            new_name="allocated_quantity",
        ),
        migrations.AlterField(
            model_name="outsourcingfactoryallocation",
            name="allocated_quantity",
            field=models.DecimalField(
                decimal_places=4,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))],
            ),
        ),
        migrations.RenameField(
            model_name="outsourcingreturnline",
            old_name="returned_quantity_sets",
            new_name="returned_quantity",
        ),
        migrations.AlterField(
            model_name="outsourcingreturnline",
            name="returned_quantity",
            field=models.DecimalField(
                decimal_places=4,
                max_digits=18,
                validators=[django.core.validators.MinValueValidator(Decimal("0.0001"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="outsourcingfactoryallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(allocated_quantity__gt=0),
                name="outs_allocation_qty_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="outsourcingprocessingitem",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="outs_processing_qty_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="outsourcingreturnline",
            constraint=models.CheckConstraint(
                condition=models.Q(returned_quantity__gt=0),
                name="outs_return_line_qty_positive",
            ),
        ),
    ]
