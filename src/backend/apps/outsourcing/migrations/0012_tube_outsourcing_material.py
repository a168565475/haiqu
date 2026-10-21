import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('outsourcing', '0011_tube_final_receipt'),
        ('material_issues', '0012_internal_receipt_source_usage'),
        ('products', '0004_seed_raw_material_information'),
        ('reference_data', '0028_fill_supplemental_accessory_units'),
    ]

    operations = [
        migrations.CreateModel(
            name='TubeOutsourcingMaterial',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=18)),
                ('snapshot', models.JSONField(default=dict)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='materials', to='outsourcing.tubeoutsourcingorder')),
                ('order_line', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='materials', to='outsourcing.tubeoutsourcingline')),
                ('bom_line', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tube_outsourcing_materials', to='boms.bomline')),
                ('requirement', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tube_outsourcing_materials', to='material_issues.ordermaterialrequirement')),
                ('raw_material', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tube_outsourcing_materials', to='products.rawmaterialinformation')),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tube_outsourcing_materials', to='reference_data.productionunit')),
                ('zone', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tube_outsourcing_materials', to='inventory.warehousezone')),
            ],
            options={
                'db_table': 'tube_outsourcing_material',
                'default_permissions': (),
                'ordering': ['order', 'created_at', 'id'],
                'indexes': [models.Index(fields=['raw_material', 'unit', 'zone'], name='tube_material_stock_idx')],
                'constraints': [
                    models.UniqueConstraint(fields=('order_line', 'bom_line', 'zone'), name='tube_material_binding_unique'),
                    models.CheckConstraint(condition=models.Q(('quantity__gt', 0)), name='tube_material_qty_positive'),
                ],
            },
        ),
    ]
