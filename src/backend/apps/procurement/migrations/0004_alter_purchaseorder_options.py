from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("procurement", "0003_purchase_order_daily_number")]

    operations = [
        migrations.AlterModelOptions(
            name="purchaseorder",
            options={
                "ordering": ["-created_at", "-id"],
                "permissions": [("submit_purchaseorder", "Can submit purchase order")],
            },
        ),
    ]
