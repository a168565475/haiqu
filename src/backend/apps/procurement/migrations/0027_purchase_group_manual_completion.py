import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0004_employee_workshop_employee_workshop_is_supervisor_and_more"),
        ("procurement", "0026_catalog_material_receipts"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchasegroup", name="manual_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="purchasegroup", name="manual_completed_by_employee",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="manually_completed_purchase_groups", to="organizations.employee",
            ),
        ),
        migrations.AddField(
            model_name="purchasegroup", name="manual_completion_remark",
            field=models.TextField(blank=True, default=""),
        ),
    ]
