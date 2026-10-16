from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0015_productiontaskproduct_customer_color_snapshot_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productiontask",
            name="customer_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="production_tasks",
                to="customers.customeraccount",
            ),
        ),
    ]
