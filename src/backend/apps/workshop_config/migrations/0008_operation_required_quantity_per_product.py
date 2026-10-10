from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("workshop_config", "0007_operation_product_name_optional")]

    operations = [
        migrations.AddField(
            model_name="operation",
            name="required_quantity_per_product",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                max_digits=18,
                null=True,
                validators=[MinValueValidator(Decimal("0.001"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="operation",
            constraint=models.CheckConstraint(
                condition=Q(required_quantity_per_product__isnull=True)
                | Q(required_quantity_per_product__gt=0),
                name="workshop_operation_required_qty_positive",
            ),
        ),
    ]
