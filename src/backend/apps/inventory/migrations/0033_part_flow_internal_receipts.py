import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0032_pipe_meter_precision')]

    operations = [
        migrations.AlterField(model_name='internalsemifinishedreceipt', name='plan_category',
            field=models.CharField(max_length=20, choices=[('METAL','金工'),('CUTTING','裁剪'),('SEWING','车缝')])),
        migrations.RemoveConstraint(model_name='internalsemifinishedreceipt', name='inv_internal_receipt_stage'),
        migrations.AddConstraint(model_name='internalsemifinishedreceipt',
            constraint=models.CheckConstraint(condition=models.Q(plan_category__in=['METAL','CUTTING','SEWING']),
                name='inv_internal_receipt_stage')),
        migrations.AlterField(model_name='internalsemifinishedreceiptline', name='input_requirement',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='internal_receipt_lines', to='material_issues.ordermaterialrequirement')),
        migrations.AlterField(model_name='internalsemifinishedreceiptline', name='input_unit_name',
            field=models.CharField(max_length=10, choices=[('支','支'),('米','米'),('片','片')])),
        migrations.RemoveConstraint(model_name='internalsemifinishedreceiptline', name='inv_int_receipt_input'),
        migrations.AddConstraint(model_name='internalsemifinishedreceiptline', constraint=models.CheckConstraint(
            condition=(models.Q(input_per_output__isnull=False,input_quantity__isnull=False,
                input_per_output__gt=0,input_quantity__gt=0,input_quantity=models.F('quantity')*models.F('input_per_output'))
                | models.Q(input_unit_name='米',input_per_output__isnull=True,input_quantity__isnull=True)
                | models.Q(input_unit_name='片',input_requirement__isnull=True,input_per_output__isnull=True,
                    input_quantity__isnull=True,attribute_snapshot__schema_version=3,
                    attribute_snapshot__semi_kind__in=['CUT_PIECE','SEWN_PART'])), name='inv_int_receipt_input')),
        migrations.RemoveConstraint(model_name='internalsemifinishedreceiptline', name='inv_int_receipt_input_unit'),
        migrations.AddConstraint(model_name='internalsemifinishedreceiptline', constraint=models.CheckConstraint(
            condition=models.Q(input_unit_name__in=['米','片']) | models.Q(input_unit_name='支',input_per_output=1),
            name='inv_int_receipt_input_unit')),
        migrations.AddConstraint(model_name='internalsemifinishedreceiptline', constraint=models.CheckConstraint(
            condition=models.Q(input_requirement__isnull=False) | models.Q(input_unit_name='片',
                attribute_snapshot__schema_version=3,attribute_snapshot__semi_kind__in=['CUT_PIECE','SEWN_PART']),
            name='inv_int_receipt_source')),
    ]
