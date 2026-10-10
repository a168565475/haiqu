from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("production_tasks", "0003_production_task_product_images"),
    ]

    operations = [
        migrations.AddField(
            model_name="productiontask",
            name="freight_amount",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0"),
                max_digits=22,
                validators=[MinValueValidator(Decimal("0"))],
            ),
        ),
        migrations.AddField(
            model_name="productiontask",
            name="other_fee_amount",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0"),
                max_digits=22,
                validators=[MinValueValidator(Decimal("0"))],
            ),
        ),
        migrations.AddConstraint(
            model_name="productiontask",
            constraint=models.CheckConstraint(
                condition=Q(freight_amount__gte=0),
                name="prod_task_freight_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="productiontask",
            constraint=models.CheckConstraint(
                condition=Q(other_fee_amount__gte=0),
                name="prod_task_other_fee_nonnegative",
            ),
        ),
    ]
