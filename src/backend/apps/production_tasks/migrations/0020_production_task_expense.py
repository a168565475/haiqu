import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('production_tasks', '0019_production_pricing_snapshots'),
        ('organizations', '0004_employee_workshop_employee_workshop_is_supervisor_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductionTaskExpense',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('expense_type', models.CharField(choices=[('LOADING', '装卸费'), ('TRANSPORT', '运输费'), ('OTHER', '其他费用')], max_length=20)),
                ('description', models.CharField(max_length=100)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=18, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))])),
                ('occurred_on', models.DateField()),
                ('remark', models.CharField(blank=True, max_length=500)),
                ('client_request_id', models.UUIDField(unique=True)),
                ('request_payload_hash', models.CharField(max_length=64)),
                ('voided_at', models.DateTimeField(blank=True, null=True)),
                ('production_task', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cost_expenses', to='production_tasks.productiontask')),
                ('created_by_employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.employee')),
                ('updated_by_employee', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.employee')),
            ],
            options={
                'ordering': ['occurred_on', 'created_at', 'id'],
                'default_permissions': (),
                'permissions': [('view_productiontaskcost', '查看订单成本'), ('manage_productiontaskexpense', '维护订单零星费用')],
                'constraints': [models.CheckConstraint(condition=models.Q(('amount__gt', 0)), name='production_task_expense_positive_amount')],
            },
        ),
    ]
