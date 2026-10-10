from django.db import migrations


TERMINAL_STATUSES = ["LOST", "CLOSED", "CANCELLED"]
EFFECTIVE_ORDER_STATUSES = ["CONFIRMED", "FULFILLING", "COMPLETED", "PAUSED"]


def backfill_order_flow_statuses(apps, schema_editor):
    Inquiry = apps.get_model("inquiries", "Inquiry")
    Quotation = apps.get_model("quotations", "Quotation")
    SalesOrder = apps.get_model("sales_orders", "SalesOrder")

    converted_ids = SalesOrder.objects.filter(
        source_quotation_version__quotation__source_inquiry_id__isnull=False,
        status__in=EFFECTIVE_ORDER_STATUSES,
        archived_at__isnull=True,
    ).values_list("source_quotation_version__quotation__source_inquiry_id", flat=True)
    Inquiry.objects.filter(pk__in=converted_ids).exclude(status__in=TERMINAL_STATUSES).update(
        status="CONVERTED"
    )

    accepted_ids = Quotation.objects.filter(
        source_inquiry_id__isnull=False,
        outcome_status="WON",
        accepted_version_id__isnull=False,
        archived_at__isnull=True,
    ).values_list("source_inquiry_id", flat=True)
    Inquiry.objects.filter(pk__in=accepted_ids).exclude(
        status__in=[*TERMINAL_STATUSES, "CONVERTED"]
    ).update(status="QUOTE_ACCEPTED")


class Migration(migrations.Migration):

    dependencies = [
        ("inquiries", "0005_inquiry_quote_accepted"),
        ("quotations", "0011_container_tier_price_and_seller_export_profile"),
        ("sales_orders", "0003_salesordercollaborationevent_quantity_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_order_flow_statuses, migrations.RunPython.noop),
    ]
