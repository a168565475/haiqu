import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0022_daily_number_format_compatibility"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="production_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_orders",
                to="production_tasks.productiontask",
            ),
        ),
    ]
