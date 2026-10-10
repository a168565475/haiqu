from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workshop_reporting", "0004_workreportline_order_quantity_snapshot")]

    operations = [
        migrations.AddField(
            model_name="wagescheme",
            name="operation_product_name_snapshot",
            field=models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
    ]
