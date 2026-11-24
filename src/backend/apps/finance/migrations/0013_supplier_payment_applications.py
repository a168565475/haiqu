import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0012_supplier_settlements'),
        ('organizations', '0004_employee_workshop_employee_workshop_is_supervisor_and_more'),
        ('procurement', '0032_pipe_meter_precision'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='supplierpayment',
            options={'default_permissions': ('add', 'view'), 'permissions': [('void_supplierpayment', '更正供应商付款')]},
        ),
        migrations.CreateModel(
            name='SupplierPaymentApplication',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('number', models.CharField(max_length=50, unique=True)),
                ('applied_on', models.DateField()),
                ('supplier_name_snapshot', models.CharField(max_length=255)),
                ('payee', models.CharField(max_length=255)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=24)),
                ('note', models.CharField(blank=True, max_length=500)),
                ('department_name_snapshot', models.CharField(blank=True, max_length=200)),
                ('recorded_by_name_snapshot', models.CharField(max_length=150)),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('withdrawal_reason', models.CharField(blank=True, max_length=500)),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.employee')),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='procurement.supplier')),
                ('withdrawn_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.employee')),
            ],
            options={
                'db_table': 'finance_supplier_payment_application',
                'permissions': [('withdraw_supplierpaymentapplication', '撤回供应商付款申请')],
                'default_permissions': ('add',),
            },
        ),
        migrations.AddField(
            model_name='supplierpayment',
            name='application',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payments', to='finance.supplierpaymentapplication'),
        ),
        migrations.CreateModel(
            name='SupplierPaymentApplicationLine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('payable_number', models.CharField(max_length=50)),
                ('inbound_date', models.DateField()),
                ('confirmed_amount', models.DecimalField(decimal_places=2, max_digits=22)),
                ('offset_amount', models.DecimalField(decimal_places=2, max_digits=22)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=22)),
                ('released_amount', models.DecimalField(decimal_places=2, default=0, max_digits=22)),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lines', to='finance.supplierpaymentapplication')),
                ('payable', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='payment_application_lines', to='finance.purchasepayable')),
            ],
            options={
                'db_table': 'finance_supplier_payment_application_line',
                'ordering': ('inbound_date', 'payable_number', 'id'),
                'default_permissions': (),
            },
        ),
        migrations.AddIndex(
            model_name='supplierpaymentapplication',
            index=models.Index(fields=['supplier', 'applied_on'], name='fin_sup_app_supplier_date'),
        ),
        migrations.AddConstraint(
            model_name='supplierpaymentapplication',
            constraint=models.CheckConstraint(condition=models.Q(('amount__gt', 0), models.Q(('payee', ''), _negated=True)), name='fin_sup_application_positive'),
        ),
        migrations.AddConstraint(
            model_name='supplierpaymentapplication',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('withdrawal_reason', ''), ('withdrawn_at__isnull', True), ('withdrawn_by__isnull', True)), models.Q(('withdrawn_at__isnull', False), ('withdrawn_by__isnull', False), models.Q(('withdrawal_reason', ''), _negated=True)), _connector='OR'), name='fin_sup_application_withdrawal'),
        ),
        migrations.AddConstraint(
            model_name='supplierpaymentapplicationline',
            constraint=models.UniqueConstraint(fields=('application', 'payable'), name='fin_sup_app_line_unique'),
        ),
        migrations.AddConstraint(
            model_name='supplierpaymentapplicationline',
            constraint=models.CheckConstraint(condition=models.Q(('amount__gt', 0), ('released_amount__gte', 0), ('released_amount__lte', models.F('amount'))), name='fin_sup_app_line_amounts'),
        ),
    ]
