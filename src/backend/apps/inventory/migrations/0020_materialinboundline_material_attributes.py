from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0019_assembly_receipt_source"),
        ("procurement", "0021_purchaseorderline_material_attributes"),
    ]

    operations = [
        migrations.AddField(
            model_name="materialinboundline",
            name="material_attributes_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
