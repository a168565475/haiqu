import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("sales_orders", "0005_salesorderline_customer_product_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="delivery_method",
            field=models.CharField(
                blank=True,
                choices=[("SINGLE", "一次交货"), ("SPLIT", "分批交货")],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="factory_merchandiser",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="factory_merchandised_sales_orders",
                to="organizations.employee",
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="tax_rate",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(3, "3%"), (5, "5%"), (7, "7%")],
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="salesorder",
            constraint=models.CheckConstraint(
                condition=Q(tax_rate__isnull=True) | Q(includes_tax=True, tax_rate__in=[3, 5, 7]),
                name="sales_order_tax_rate_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="salesorder",
            constraint=models.CheckConstraint(
                condition=Q(delivery_method__isnull=True) | Q(delivery_method__in=["SINGLE", "SPLIT"]),
                name="sales_order_delivery_method_valid",
            ),
        ),
    ]
