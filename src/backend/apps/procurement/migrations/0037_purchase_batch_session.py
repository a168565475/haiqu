from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0036_purchase_group_bom_sources"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="batch_session_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="purchaseorder",
            name="purchase_group_batch_number_uniq",
        ),
        migrations.AddConstraint(
            model_name="purchaseorder",
            constraint=models.UniqueConstraint(
                fields=("purchase_group", "batch_number"),
                condition=models.Q(batch_session_id__isnull=True),
                name="purchase_group_batch_number_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseorder",
            index=models.Index(fields=["purchase_group", "batch_session_id"], name="po_group_batch_session_idx"),
        ),
    ]
