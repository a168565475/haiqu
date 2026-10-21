from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0020_materialinboundline_material_attributes'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='internalsemifinishedreceiptline', name='inv_int_receipt_input',
        ),
        migrations.AlterField(
            model_name='internalsemifinishedreceiptline', name='input_per_output',
            field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='internalsemifinishedreceiptline', name='input_quantity',
            field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True),
        ),
        migrations.AddConstraint(
            model_name='internalsemifinishedreceiptline',
            constraint=models.CheckConstraint(
                condition=models.Q(input_per_output__isnull=False, input_quantity__isnull=False,
                                   input_per_output__gt=0, input_quantity__gt=0,
                                   input_quantity=models.F('quantity') * models.F('input_per_output'))
                          | models.Q(input_unit_name='米', input_per_output__isnull=True, input_quantity__isnull=True),
                name='inv_int_receipt_input',
            ),
        ),
    ]
