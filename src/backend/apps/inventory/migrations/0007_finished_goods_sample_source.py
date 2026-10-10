import django.db.models.deletion
from django.db import migrations, models


def backfill_production_sources(apps, schema_editor):
    receipt_model = apps.get_model("inventory", "FinishedGoodsReceipt")
    receipt_model.objects.filter(source_document_number="").update(
        source_document_number=models.F("task_number_snapshot")
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0006_material_inbound_zone_optional_location"),
        ("samples", "0020_sample_inventory_loan_sequence"),
    ]

    operations = [
        migrations.AlterField(
            model_name="finishedgoodsreceipt",
            name="production_task_product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="finished_goods_receipts",
                to="production_tasks.productiontaskproduct",
            ),
        ),
        migrations.AddField(
            model_name="finishedgoodsreceipt",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("PRODUCTION_ORDER", "生产订单入库"),
                    ("SAMPLE_INVENTORY", "样品入库"),
                ],
                default="PRODUCTION_ORDER",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="finishedgoodsreceipt",
            name="source_document_number",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="finishedgoodsreceipt",
            name="source_sample_inventory_line",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="finished_goods_receipt",
                to="samples.sampleinventoryline",
            ),
        ),
        migrations.RunPython(backfill_production_sources, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="finishedgoodsreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(source_type__in=["PRODUCTION_ORDER", "SAMPLE_INVENTORY"]),
                name="inv_receipt_source_type_valid",
            ),
        ),
    ]
