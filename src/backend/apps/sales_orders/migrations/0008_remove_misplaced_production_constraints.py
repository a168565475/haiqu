from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("sales_orders", "0007_merge_confirmation_and_product_snapshots")]
    operations = [
        migrations.RemoveConstraint(model_name="salesorder", name="sales_order_tax_rate_consistent"),
        migrations.RemoveConstraint(model_name="salesorder", name="sales_order_delivery_method_valid"),
    ]
