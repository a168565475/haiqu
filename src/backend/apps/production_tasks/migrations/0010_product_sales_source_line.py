from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0009_productionrunbatch_and_more"),
        ("sales_orders", "0004_salesorder_buyer_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontaskproduct",
            name="sales_order_delivery_batch_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="production_task_products",
                to="sales_orders.salesorderdeliverybatchline",
            ),
        ),
    ]
