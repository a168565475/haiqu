from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("procurement", "0036_purchase_batch_session")]

    operations = [
        migrations.AddField(
            model_name="purchasegroup", name="purchase_scope",
            field=models.CharField(
                choices=[("STANDARD", "普通采购"), ("PACKAGING", "包材采购")],
                default="STANDARD", db_default="STANDARD", max_length=12,
            ),
        ),
        migrations.AlterModelOptions(
            name="purchasegroup",
            options={"ordering": ["-created_at", "-id"], "permissions": [("manage_packagingpurchase", "办理包材采购")]},
        ),
    ]
