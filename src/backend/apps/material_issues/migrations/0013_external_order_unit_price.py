from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("material_issues", "0012_internal_receipt_source_usage")]

    operations = [
        migrations.AddField(
            model_name="metalprocessingexternalorder", name="unit_price",
            field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name="metalprocessingexternalorder",
            constraint=models.CheckConstraint(
                condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gte=0),
                name="metal_p4_order_price_nonnegative",
            ),
        ),
    ]
