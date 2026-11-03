from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("boms", "0012_cutting_quantity_without_meters"),
        ("material_catalog", "0003_catalog_warehouses_and_labels"),
    ]
    operations = [
        migrations.AddField(
            model_name="bomline", name="material_catalog",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="bom_lines", to="material_catalog.materialcatalog"),
        ),
        migrations.AddField(
            model_name="bomline", name="material_selection_snapshot", field=models.JSONField(default=dict, blank=True),
        ),
    ]
