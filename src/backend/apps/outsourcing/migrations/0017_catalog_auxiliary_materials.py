import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('outsourcing', '0016_processing_material_snapshots')]

    operations = [
        migrations.AlterField(model_name='tubeoutsourcingmaterial', name='raw_material',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='tube_outsourcing_materials', to='products.rawmaterialinformation')),
        migrations.AddField(model_name='tubeoutsourcingmaterial', name='material_catalog',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='outsourcing_auxiliary_materials', to='material_catalog.materialcatalog')),
        migrations.AddField(model_name='tubeoutsourcingmaterial', name='material_selection_snapshot',
            field=models.JSONField(blank=True, default=dict)),
        migrations.AddConstraint(model_name='tubeoutsourcingmaterial',
            constraint=models.CheckConstraint(condition=(
                models.Q(raw_material__isnull=False, material_catalog__isnull=True)
                | models.Q(raw_material__isnull=True, material_catalog__isnull=False)),
                name='tube_material_source_valid')),
    ]
