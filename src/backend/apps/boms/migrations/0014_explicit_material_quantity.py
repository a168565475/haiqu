from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("boms", "0013_catalog_material_selection")]
    operations = [
        migrations.AddField(
            model_name="bomline", name="material_quantity",
            field=models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True),
        ),
    ]
