from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0038_pending_cutting_receipt_zone')]

    operations = [
        migrations.RemoveConstraint(
            model_name='internalsemifinishedreceipt',
            name='inv_internal_receipt_zone_required',
        ),
        migrations.AddConstraint(
            model_name='internalsemifinishedreceipt',
            constraint=models.CheckConstraint(
                condition=models.Q(zone__isnull=False) | models.Q(status='PENDING'),
                name='inv_internal_receipt_zone_required',
            ),
        ),
    ]
