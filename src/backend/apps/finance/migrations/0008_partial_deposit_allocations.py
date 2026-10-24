from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0007_void_document_delete_permissions")]

    operations = [
        migrations.RemoveConstraint(
            model_name="depositallocation", name="finance_deposit_active_allocation",
        ),
        migrations.AddConstraint(
            model_name="depositallocation",
            constraint=models.UniqueConstraint(
                fields=["goods_receipt", "deposit_receipt"], name="finance_goods_deposit_unique",
            ),
        ),
    ]
