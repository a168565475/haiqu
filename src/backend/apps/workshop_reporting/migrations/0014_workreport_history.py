import uuid

from django.db import migrations, models


def backfill_report_history(apps, schema_editor):
    Report = apps.get_model('workshop_reporting', 'WorkReport')
    History = apps.get_model('workshop_reporting', 'WorkReportHistory')
    alias = schema_editor.connection.alias
    batch = []
    for row in Report.objects.using(alias).all().iterator(chunk_size=500):
        batch.append(History(client_request_id=row.client_request_id, report_id=row.pk,
                             report_number=row.report_number, request_payload_hash=row.request_payload_hash,
                             used_scheme_ids=[str(row.scheme_id)]))
        if len(batch) == 500:
            History.objects.using(alias).bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        History.objects.using(alias).bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [('workshop_reporting', '0013_work_plan_progress_and_required_quantity')]
    operations = [
        migrations.CreateModel(
            name='WorkReportHistory',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client_request_id', models.UUIDField(unique=True)),
                ('report_id', models.UUIDField(unique=True)),
                ('report_number', models.CharField(max_length=50)),
                ('request_payload_hash', models.CharField(max_length=64)),
                ('used_scheme_ids', models.JSONField(default=list)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('deleted_by_employee_id', models.UUIDField(blank=True, null=True)),
                ('deleted_by_name', models.CharField(blank=True, max_length=150)),
                ('deletion_reason', models.CharField(blank=True, max_length=1000)),
                ('deletion_snapshot', models.JSONField(default=dict)),
            ],
            options={'db_table': 'workshop_work_report_history', 'default_permissions': ()},
        ),
        migrations.RunPython(backfill_report_history, migrations.RunPython.noop),
    ]
