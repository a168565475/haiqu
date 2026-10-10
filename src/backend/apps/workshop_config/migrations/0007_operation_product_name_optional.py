from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workshop_config", "0006_operation_reporting_unit")]

    operations = [
        migrations.AlterField(
            model_name="operation",
            name="product_name",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
