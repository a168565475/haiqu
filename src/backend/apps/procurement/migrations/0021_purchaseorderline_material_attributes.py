from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("procurement", "0020_expand_daily_purchase_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="material_attributes_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
