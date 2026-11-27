import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0037_pending_finished_receipt_location')]

    operations = [
        migrations.AlterField(
            model_name='internalsemifinishedreceipt',
            name='zone',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='internal_semi_receipts', to='inventory.warehousezone',
            ),
        ),
        migrations.AddConstraint(
            model_name='internalsemifinishedreceipt',
            constraint=models.CheckConstraint(
                condition=models.Q(zone__isnull=False) | models.Q(status='PENDING', plan_category='CUTTING'),
                name='inv_internal_receipt_zone_required',
            ),
        ),
    ]
