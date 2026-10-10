import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0008_alter_materialinbound_options_and_more"),
        ("products", "0004_seed_raw_material_information"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialinbound",
            name="client_request_id",
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="materialinboundline",
            name="purchase_order_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="material_inbound_lines",
                to="procurement.purchaseorderline",
            ),
        ),
        migrations.AddField(
            model_name="materialinboundline",
            name="raw_material_information",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="manual_inbound_lines",
                to="products.rawmaterialinformation",
            ),
        ),
        migrations.AddConstraint(
            model_name="materialinboundline",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(purchase_order_line__isnull=False, raw_material_information__isnull=True)
                    | models.Q(purchase_order_line__isnull=True, raw_material_information__isnull=False)
                ),
                name="inv_mat_line_source_valid",
            ),
        ),
    ]
