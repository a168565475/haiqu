from uuid import UUID

import django.db.models.deletion
from django.db import migrations, models


def backfill_quotation_address(apps, schema_editor):
    SalesOrder = apps.get_model("sales_orders", "SalesOrder")
    CustomerEntityAddress = apps.get_model("customers", "CustomerEntityAddress")

    orders = SalesOrder.objects.filter(
        source_type="QUOTATION",
        source_quotation_version__isnull=False,
    ).select_related("source_quotation_version")
    for order in orders.iterator(chunk_size=500):
        snapshot = dict(order.source_quotation_version.address_snapshot or {})
        order.buyer_address_snapshot = snapshot
        raw_address_id = snapshot.get("id")
        address_id = None
        if raw_address_id:
            try:
                address_id = UUID(str(raw_address_id))
            except (TypeError, ValueError):
                address_id = None
        if address_id and CustomerEntityAddress.objects.filter(
            pk=address_id,
            transaction_entity_id=order.transaction_entity_id,
        ).exists():
            order.buyer_address_id = address_id
        order.save(update_fields=["buyer_address", "buyer_address_snapshot"])


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0013_remove_customer_credit_grade"),
        ("sales_orders", "0003_salesordercollaborationevent_quantity_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="buyer_address",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sales_orders",
                to="customers.customerentityaddress",
            ),
        ),
        migrations.AddField(
            model_name="salesorder",
            name="buyer_address_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(backfill_quotation_address, migrations.RunPython.noop),
    ]
