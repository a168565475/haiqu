from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0021_active_task_number_unique"),
        ("product_catalog", "0002_product_materials_thicknesses"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontaskproduct",
            name="product_catalog",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="production_task_products", to="product_catalog.productcatalog"),
        ),
        migrations.AddField(
            model_name="productiontaskproduct",
            name="product_selection_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="productiontaskproduct",
            constraint=models.CheckConstraint(
                condition=models.Q(product__isnull=True) | models.Q(product_catalog__isnull=True),
                name="prod_task_product_source_exclusive",
            ),
        ),
    ]
