import django.db.models.deletion
from django.db import migrations, models


def copy_material_factories(apps, schema_editor):
    Material = apps.get_model('outsourcing', 'TubeOutsourcingMaterial')
    for material in Material.objects.using(schema_editor.connection.alias).select_related('order_line').iterator():
        material.factory_id = material.order_line.factory_id
        material.save(using=schema_editor.connection.alias, update_fields=['factory'])


class Migration(migrations.Migration):
    dependencies = [('outsourcing', '0012_tube_outsourcing_material')]

    operations = [
        migrations.AddField(model_name='tubeoutsourcingline', name='unit_price',
            field=models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)),
        migrations.AddConstraint(model_name='tubeoutsourcingline',
            constraint=models.CheckConstraint(condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gte=0),
                                              name='tube_line_price_nonnegative')),
        migrations.AddField(model_name='tubeoutsourcingmaterial', name='factory',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='tube_outsourcing_materials', to='outsourcing.outsourcingfactory')),
        migrations.RunPython(copy_material_factories, migrations.RunPython.noop),
        migrations.AlterField(model_name='tubeoutsourcingmaterial', name='factory',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='tube_outsourcing_materials', to='outsourcing.outsourcingfactory')),
        migrations.AlterField(model_name='tubeoutsourcingmaterial', name='order_line',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='materials', to='outsourcing.tubeoutsourcingline')),
        migrations.AddConstraint(model_name='tubeoutsourcingmaterial',
            constraint=models.UniqueConstraint(fields=['order', 'bom_line', 'factory', 'zone'],
                condition=models.Q(order_line__isnull=True), name='tube_material_factory_unique')),
    ]
