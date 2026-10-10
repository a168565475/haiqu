import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0004_seed_raw_material_information"),
        ("reference_data", "0026_number_rule_yearly_reset"),
    ]

    operations = [
        migrations.AddField(
            model_name="fabricmaterial",
            name="inventory_raw_material",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fabric_material_mappings",
                to="products.rawmaterialinformation",
            ),
        ),
        migrations.AddField(
            model_name="accessorymaterial",
            name="inventory_raw_material",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="accessory_material_mappings",
                to="products.rawmaterialinformation",
            ),
        ),
    ]
