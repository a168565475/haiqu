import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("boms", "0002_bomlineimage"),
        ("files", "0003_businessfile_scan_status_skipped"),
    ]

    operations = [
        migrations.CreateModel(
            name="BomLineImageDraft",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("draft_key", models.UUIDField()),
                ("position", models.PositiveIntegerField()),
                ("expires_at", models.DateTimeField()),
                (
                    "bom",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="line_image_drafts",
                        to="boms.bom",
                    ),
                ),
                (
                    "business_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bom_line_image_drafts",
                        to="files.businessfile",
                    ),
                ),
                (
                    "owner_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bom_line_image_drafts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "bom_line_image_draft",
                "ordering": ["bom", "owner_user", "draft_key", "position", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("bom", "owner_user", "draft_key", "position"),
                        name="bom_image_draft_position_unique",
                    ),
                    models.UniqueConstraint(
                        fields=("business_file",),
                        name="bom_image_draft_file_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("position__gt", 0)),
                        name="bom_image_draft_position_positive",
                    ),
                ],
                "indexes": [
                    models.Index(fields=["expires_at", "id"], name="bom_image_draft_expiry_idx"),
                    models.Index(
                        fields=["bom", "owner_user", "draft_key", "position"],
                        name="bom_image_draft_scope_idx",
                    ),
                ],
            },
        ),
    ]
