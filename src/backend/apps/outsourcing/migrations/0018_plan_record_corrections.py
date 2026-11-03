import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('outsourcing', '0017_catalog_auxiliary_materials')]

    operations = [
        migrations.AddField(model_name='tubeplanreceipt', name='voided_at',
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.CreateModel(
            name='TubePlanRecordCorrection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client_request_id', models.UUIDField(unique=True)),
                ('request_payload_hash', models.CharField(max_length=64)),
                ('record_kind', models.CharField(choices=[('DISPATCH', '外发'), ('RECEIPT', '入库')], max_length=8)),
                ('record_id', models.UUIDField()),
                ('operation', models.CharField(choices=[('UPDATE', '调整'), ('DELETE', '删除整次')], max_length=6)),
                ('before_data', models.JSONField(default=dict)),
                ('after_data', models.JSONField(default=dict)),
                ('stock_movements', models.JSONField(default=list)),
                ('actor_employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='outsourcing_plan_corrections', to='organizations.employee')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='record_corrections', to='outsourcing.tubeoutsourcingorder')),
            ],
            options={'db_table': 'tube_plan_record_correction', 'default_permissions': (),
                     'ordering': ['created_at', 'pk'], 'constraints': [
                         models.CheckConstraint(condition=models.Q(record_kind__in=['DISPATCH', 'RECEIPT']),
                                                name='tube_correction_kind_valid'),
                         models.CheckConstraint(condition=models.Q(operation__in=['UPDATE', 'DELETE']),
                                                name='tube_correction_operation_valid'),
                     ]},
        ),
    ]
