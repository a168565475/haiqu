import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales_orders", "0008_remove_misplaced_production_constraints"),
        ("reference_data", "0007_exchangerate_incoterm_paymentmethod_port_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="salesorder", name="exchange_rate",
            field=models.DecimalField(max_digits=22, decimal_places=8, default=Decimal("1"),
                                      validators=[django.core.validators.MinValueValidator(Decimal("0.00000001"))]),
        ),
        migrations.AddField(
            model_name="salesorder", name="exchange_rate_record",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="sales_orders", to="reference_data.exchangerate"),
        ),
        migrations.AddField(model_name="salesorder", name="exchange_rate_snapshot", field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name="salesorder", name="total_amount_cny", field=models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)),
        migrations.AddField(model_name="salesorderline", name="unit_price_cny", field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)),
        migrations.AddField(model_name="salesorderline", name="line_total_cny", field=models.DecimalField(max_digits=22, decimal_places=4, null=True, blank=True)),
        migrations.AddConstraint(model_name="salesorder", constraint=models.CheckConstraint(condition=models.Q(total_amount_cny__gte=0), name="sales_order_cny_total_nonneg")),
        migrations.AddConstraint(model_name="salesorderline", constraint=models.CheckConstraint(condition=models.Q(unit_price_cny__gte=0), name="sales_order_line_cny_price_nonneg")),
        migrations.AddConstraint(model_name="salesorderline", constraint=models.CheckConstraint(condition=models.Q(line_total_cny__gte=0), name="sales_order_line_cny_total_nonneg")),
    ]
