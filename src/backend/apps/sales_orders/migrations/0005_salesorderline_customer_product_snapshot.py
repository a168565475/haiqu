import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales_orders", "0004_salesorder_buyer_address"),
    ]

    operations = [
        migrations.AlterField(
            model_name="salesorderline",
            name="product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sales_order_lines",
                to="products.productinformation",
            ),
        ),
        migrations.AddField(
            model_name="salesorderline",
            name="customer_product_name_snapshot",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="salesorderline",
            name="customer_specification_snapshot",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="salesorderline",
            name="customer_color_snapshot",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
