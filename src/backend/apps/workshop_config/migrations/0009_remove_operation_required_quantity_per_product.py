from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("workshop_config", "0008_operation_required_quantity_per_product")]

    operations = [
        migrations.RemoveConstraint(
            model_name="operation",
            name="workshop_operation_required_qty_positive",
        ),
        migrations.RemoveField(
            model_name="operation",
            name="required_quantity_per_product",
        ),
    ]
