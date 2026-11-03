import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [('organizations', '0004_employee_workshop_employee_workshop_is_supervisor_and_more')]

    operations = [
        migrations.CreateModel(
            name='CodexConnection',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('singleton', models.PositiveSmallIntegerField(default=1, unique=True)),
                ('config_generation', models.PositiveBigIntegerField(default=1)),
                ('status', models.CharField(choices=[('DISCONNECTED', '未连接'), ('CONNECTED', '已连接未测试'),
                    ('READY', '可用'), ('LOGIN_PENDING', '等待授权'), ('DRAINING', '等待当前操作结束'),
                    ('ERROR', '失败'), ('UNKNOWN', '待核实')], default='DISCONNECTED', max_length=20)),
                ('selected_model', models.CharField(blank=True, max_length=200)),
                ('cli_version', models.CharField(blank=True, max_length=64)),
                ('account', models.JSONField(blank=True, default=None, null=True)),
                ('available_models', models.JSONField(default=list)),
                ('rate_limits', models.JSONField(blank=True, default=None, null=True)),
                ('limits_updated_at', models.DateTimeField(blank=True, null=True)),
                ('last_checked_at', models.DateTimeField(blank=True, null=True)),
                ('last_test_at', models.DateTimeField(blank=True, null=True)),
                ('error_code', models.CharField(blank=True, max_length=64)),
                ('paused', models.BooleanField(default=True)),
            ],
            options={'db_table': 'codex_connection', 'default_permissions': (), 'constraints': [
                models.CheckConstraint(condition=models.Q(singleton=1), name='codex_connection_singleton'),
                models.CheckConstraint(condition=models.Q(config_generation__gte=1), name='codex_generation_positive'),
                models.CheckConstraint(condition=models.Q(status__in=['DISCONNECTED', 'CONNECTED', 'READY', 'LOGIN_PENDING', 'DRAINING', 'ERROR', 'UNKNOWN']), name='codex_connection_status_valid'),
            ]},
        ),
        migrations.CreateModel(
            name='CodexOperation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('action', models.CharField(choices=[('login', 'login'), ('switch', 'switch'), ('disconnect', 'disconnect'), ('refresh', 'refresh'), ('test', 'test')], max_length=12)),
                ('state', models.CharField(choices=[('QUEUED', '待执行'), ('RUNNING', '执行中'), ('CANCELING', '正在取消'),
                    ('SUCCEEDED', '已完成'), ('FAILED', '失败'), ('CANCELED', '已取消'), ('INTERRUPTED', '中断待核实')], default='QUEUED', max_length=16)),
                ('generation', models.PositiveBigIntegerField(default=1)),
                ('model', models.CharField(blank=True, max_length=200)),
                ('attempt_no', models.PositiveIntegerField(default=0)),
                ('lease_id', models.UUIDField(blank=True, null=True)),
                ('lease_expires_at', models.DateTimeField(blank=True, null=True)),
                ('runtime_boot_id', models.UUIDField(blank=True, null=True)),
                ('cancel_sent', models.BooleanField(default=False)),
                ('error_code', models.CharField(blank=True, max_length=64)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('request_id', models.UUIDField(blank=True, null=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='codex_operations', to='organizations.employee')),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='operations', to='codex_connection.codexconnection')),
            ],
            options={'db_table': 'codex_operation', 'default_permissions': (), 'ordering': ['created_at', 'id'], 'constraints': [
                models.UniqueConstraint(fields=['connection'], condition=models.Q(state__in=('RUNNING', 'CANCELING')), name='codex_one_running_operation'),
                models.UniqueConstraint(fields=['connection'], condition=models.Q(state='QUEUED'), name='codex_one_queued_operation'),
                models.CheckConstraint(condition=models.Q(state__in=['QUEUED', 'RUNNING', 'CANCELING', 'SUCCEEDED', 'FAILED', 'CANCELED', 'INTERRUPTED']), name='codex_operation_state_valid'),
                models.CheckConstraint(condition=models.Q(action__in=('login', 'switch', 'disconnect', 'refresh', 'test')), name='codex_operation_action_valid'),
                models.CheckConstraint(condition=models.Q(generation__gte=1), name='codex_operation_generation_positive'),
            ]},
        ),
    ]
