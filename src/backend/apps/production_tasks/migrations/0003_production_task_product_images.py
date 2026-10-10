import uuid

import django.db.models.deletion
from django.db import migrations, models


def copy_legacy_product_images(apps, schema_editor):
    product_line_model = apps.get_model("production_tasks", "ProductionTaskProduct")
    product_image_model = apps.get_model("production_tasks", "ProductionTaskProductImage")
    rows = product_line_model.objects.exclude(image_file_id__isnull=True).values("id", "image_file_id")
    product_image_model.objects.bulk_create(
        [
            product_image_model(
                product_line_id=row["id"],
                line_number=1,
                image_file_id=row["image_file_id"],
            )
            for row in rows
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0001_initial"),
        ("production_tasks", "0002_production_task_number_rules"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductionTaskProductImage",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("line_number", models.PositiveIntegerField()),
                (
                    "image_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="production_task_product_images",
                        to="files.businessfile",
                    ),
                ),
                (
                    "product_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="images",
                        to="production_tasks.productiontaskproduct",
                    ),
                ),
            ],
            options={
                "db_table": "production_task_product_image",
                "ordering": ["product_line", "line_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="productiontaskproductimage",
            constraint=models.UniqueConstraint(
                fields=("product_line", "line_number"),
                name="prod_task_product_image_line_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="productiontaskproductimage",
            constraint=models.UniqueConstraint(
                fields=("product_line", "image_file"),
                name="prod_task_product_image_file_unique",
            ),
        ),
        migrations.RunPython(copy_legacy_product_images, migrations.RunPython.noop),
    ]
