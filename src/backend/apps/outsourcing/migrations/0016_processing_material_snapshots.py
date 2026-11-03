import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('outsourcing', '0015_plan_batches'),
        ('material_catalog', '0003_catalog_warehouses_and_labels'),
    ]
    operations = [
        migrations.AddField(model_name='tubeoutsourcingline', name='input_material_catalog',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='outsourcing_input_lines', to='material_catalog.materialcatalog')),
        migrations.AddField(model_name='tubeoutsourcingline', name='output_material_catalog',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='outsourcing_output_lines', to='material_catalog.materialcatalog')),
        migrations.AddField(model_name='tubeoutsourcingline', name='input_material_selection_snapshot',
            field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='tubeoutsourcingline', name='output_material_selection_snapshot',
            field=models.JSONField(blank=True, default=dict)),
    ]
