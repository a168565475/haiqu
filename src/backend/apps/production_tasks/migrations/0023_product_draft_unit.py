from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("production_tasks", "0022_product_catalog_selection")]

    operations = [
        migrations.AlterField(
            model_name="productiontaskproduct",
            name="unit",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="production_task_products", to="reference_data.productionunit",
            ),
        ),
    ]
