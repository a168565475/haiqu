from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("organizations", "0004_employee_workshop_employee_workshop_is_supervisor_and_more"),
    ]
    operations = [
        migrations.CreateModel(
            name="OpenAIKeyConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=100)),
                ("provider", models.CharField(default="openai", max_length=50)),
                ("model", models.CharField(default="gpt-6-astra", max_length=100)),
                ("base_url", models.URLField(blank=True, default="", max_length=500)),
                ("key_ciphertext", models.TextField()),
                ("key_last4", models.CharField(max_length=4)),
                ("key_fingerprint", models.CharField(max_length=64)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="openai_key_configs", to="organizations.employee")),
            ],
            options={
                "db_table": "ai_openai_key_config",
                "ordering": ["label", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="openaikeyconfig",
            constraint=models.UniqueConstraint(fields=("employee", "label"), name="ai_openai_key_employee_label_uniq"),
        ),
        migrations.AddIndex(
            model_name="openaikeyconfig",
            index=models.Index(fields=["employee", "label"], name="ai_openai_key_employee_idx"),
        ),
    ]
