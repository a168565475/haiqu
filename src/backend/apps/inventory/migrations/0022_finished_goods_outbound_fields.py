import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0021_sewing_receipt_without_meter_usage")]

    operations = [
        migrations.AddField("finishedgoodsreceipt", "material_snapshot", models.TextField(blank=True)),
        migrations.AddField("finishedgoodsoutbound", "responsible_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="responsible_finished_goods_outbounds", to="organizations.employee")),
        migrations.AddField("finishedgoodsoutbound", "responsible_name_snapshot", models.CharField(blank=True, max_length=150)),
        migrations.AddField("finishedgoodsoutbound", "shipment_date", models.DateField(blank=True, null=True)),
        migrations.AddField("finishedgoodsoutbound", "loading_fee", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.AddField("finishedgoodsoutbound", "other_fee", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
        migrations.CreateModel(
            name="FinishedGoodsOutboundAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("outbound", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attachments", to="inventory.finishedgoodsoutbound")),
                ("business_file", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="finished_goods_outbound_attachments", to="files.businessfile")),
            ],
            options={"db_table": "inventory_finished_goods_outbound_attachment", "ordering": ["created_at", "id"]},
        ),
        migrations.AddConstraint("finishedgoodsoutboundattachment", models.UniqueConstraint(fields=("outbound", "business_file"), name="inv_outbound_file_uniq")),
    ]
