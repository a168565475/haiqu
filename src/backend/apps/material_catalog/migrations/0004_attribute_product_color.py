import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("material_catalog", "0003_catalog_warehouses_and_labels"),
        ("reference_data", "0031_material_public_configuration"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialattributevalue", name="product_color",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="catalog_color_options", to="reference_data.productcolor"),
        ),
        migrations.RemoveConstraint(model_name="materialattributevalue", name="mat_catalog_value_uniq"),
        migrations.AddConstraint(
            model_name="materialattributevalue",
            constraint=models.UniqueConstraint(
                fields=("catalog", "scope", "field_key", "value", "parent"), nulls_distinct=False,
                condition=models.Q(product_color__isnull=True), name="mat_catalog_value_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="materialattributevalue",
            constraint=models.UniqueConstraint(fields=("catalog", "scope", "field_key", "product_color"),
                                              condition=models.Q(product_color__isnull=False), name="mat_catalog_color_uniq"),
        ),
        migrations.AddConstraint(
            model_name="materialattributevalue",
            constraint=models.CheckConstraint(
                condition=models.Q(product_color__isnull=True) | models.Q(scope="BASE", field_key="color"),
                name="mat_catalog_color_field_valid",
            ),
        ),
    ]
