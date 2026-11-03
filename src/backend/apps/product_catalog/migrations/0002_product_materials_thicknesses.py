from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("product_catalog", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="productcatalog", name="materials",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="productcatalog", name="thicknesses",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
