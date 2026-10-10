import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizations", "0002_seed_root_organization"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailAccount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("display_name", models.CharField(max_length=100)),
                ("sender_name", models.CharField(blank=True, max_length=150)),
                ("sender_email", models.EmailField(max_length=254)),
                ("smtp_host", models.CharField(max_length=255)),
                ("smtp_port", models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(65535)])),
                ("smtp_username", models.CharField(max_length=254)),
                ("smtp_password_ciphertext", models.TextField()),
                ("smtp_security", models.CharField(choices=[("STARTTLS", "STARTTLS"), ("SSL", "SSL/TLS")], max_length=20)),
                ("is_enabled", models.BooleanField(default=True)),
                ("is_default", models.BooleanField(default=False)),
                ("last_test_status", models.CharField(choices=[("NOT_TESTED", "未测试"), ("SUCCESS", "测试成功"), ("FAILED", "测试失败")], default="NOT_TESTED", max_length=20)),
                ("last_tested_at", models.DateTimeField(blank=True, null=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="email_accounts", to="organizations.employee")),
            ],
            options={
                "db_table": "email_account",
                "ordering": ["employee", "-is_default", "display_name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="emailaccount",
            constraint=models.UniqueConstraint(fields=("employee", "display_name"), name="email_account_employee_display_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="emailaccount",
            constraint=models.UniqueConstraint(condition=Q(("is_default", True)), fields=("employee",), name="email_account_one_default_per_employee"),
        ),
        migrations.AddConstraint(
            model_name="emailaccount",
            constraint=models.CheckConstraint(condition=Q(("smtp_port__gte", 1), ("smtp_port__lte", 65535)), name="email_account_smtp_port_valid"),
        ),
        migrations.AddConstraint(
            model_name="emailaccount",
            constraint=models.CheckConstraint(condition=Q(("is_default", False)) | Q(("is_enabled", True)), name="email_account_default_requires_enabled"),
        ),
        migrations.AddIndex(
            model_name="emailaccount",
            index=models.Index(fields=["employee", "is_enabled", "is_default"], name="email_acct_sender_idx"),
        ),
    ]
