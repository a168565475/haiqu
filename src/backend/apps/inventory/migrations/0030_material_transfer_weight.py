from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("inventory", "0029_pipe_weight_quantities")]

    operations = [
        migrations.AddField(
            model_name="materialtransferline",
            name="weight_quantity",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=22, null=True),
        ),
        migrations.AddConstraint(
            model_name="materialtransferline",
            constraint=models.CheckConstraint(
                condition=models.Q(weight_quantity__isnull=True) | models.Q(weight_quantity__gte=0),
                name="inv_transfer_line_weight_nonnegative",
            ),
        ),
    ]
