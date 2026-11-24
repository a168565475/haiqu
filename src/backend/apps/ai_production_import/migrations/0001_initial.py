from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0004_employee_workshop_employee_workshop_is_supervisor_and_more")]
    operations = [
        migrations.CreateModel(
            name="AiProductionImport",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client_request_id", models.UUIDField()),
                ("original_name", models.CharField(max_length=255)),
                ("sha256", models.CharField(max_length=64)),
                ("size_bytes", models.PositiveIntegerField()),
                ("state", models.CharField(choices=[("REVIEW", "待核对"), ("FAILED", "失败"), ("TASK_DRAFT", "任务草稿已创建"), ("BOM_PENDING", "BOM待确认")], default="REVIEW", max_length=20)),
                ("model", models.CharField(blank=True, max_length=100)),
                ("source", models.JSONField(default=dict)),
                ("result", models.JSONField(default=dict)),
                ("issues", models.JSONField(default=list)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("task_id", models.UUIDField(blank=True, null=True)),
                ("task_number", models.CharField(blank=True, max_length=50)),
                ("bom_id", models.UUIDField(blank=True, null=True)),
                ("bom_ids", models.JSONField(default=list)),
                ("created_by_employee_id", models.UUIDField(blank=True, null=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ai_production_imports", to="organizations.employee")),
            ],
            options={"db_table": "ai_production_import", "default_permissions": ()},
        ),
        migrations.AddConstraint(
            model_name="aiproductionimport",
            constraint=models.UniqueConstraint(fields=("owner", "client_request_id"), name="ai_import_request_unique"),
        ),
        migrations.AddIndex(
            model_name="aiproductionimport",
            index=models.Index(fields=["owner", "-created_at"], name="ai_import_owner_created_idx"),
        ),
    ]
