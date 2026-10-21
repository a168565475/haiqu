from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('outsourcing', '0013_tube_material_factory_and_price')]

    operations = [
        migrations.RemoveConstraint(model_name='tubeoutsourcingorder', name='tube_order_source_valid'),
        migrations.RemoveConstraint(model_name='tubeoutsourcingorder', name='tube_order_zone_shape'),
        migrations.AlterField(model_name='tubeoutsourcingorder', name='source_kind',
            field=models.CharField(max_length=16, choices=[('RAW_PIPE', '公共原管材'),
                ('PUBLIC_SEMI', '公共未喷塑半成品'), ('METAL', '厂内已加工件'),
                ('PUBLIC_CUTTING', '已入库裁片半成品'), ('SEWING', '未入库车缝完成件')])),
        migrations.AddConstraint(model_name='tubeoutsourcingorder',
            constraint=models.CheckConstraint(condition=models.Q(source_kind__in=[
                'RAW_PIPE', 'PUBLIC_SEMI', 'METAL', 'PUBLIC_CUTTING', 'SEWING']), name='tube_order_source_valid')),
        migrations.AddConstraint(model_name='tubeoutsourcingorder',
            constraint=models.CheckConstraint(condition=(models.Q(source_kind__in=['METAL', 'SEWING'], zone__isnull=True)
                | models.Q(source_kind__in=['RAW_PIPE', 'PUBLIC_SEMI', 'PUBLIC_CUTTING'], zone__isnull=False)),
                name='tube_order_zone_shape')),
    ]
