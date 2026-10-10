import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0001_initial"),
        ("samples", "0013_sam10_production_workflow"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleProductSamplingDetail",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("line_number", models.PositiveIntegerField()),
                ("template_key", models.CharField(blank=True, max_length=64)),
                ("detail_type", models.CharField(max_length=100)),
                ("category_label", models.CharField(blank=True, max_length=100)),
                ("is_selected", models.BooleanField(default=False)),
                ("description", models.TextField(blank=True)),
                (
                    "image_file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_product_sampling_details",
                        to="files.businessfile",
                    ),
                ),
                (
                    "sample_product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sampling_details",
                        to="samples.sampleproduct",
                    ),
                ),
            ],
            options={
                "db_table": "sample_product_sampling_detail",
                "ordering": ["sample_product", "line_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleproductsamplingdetail",
            constraint=models.UniqueConstraint(
                fields=("sample_product", "line_number"),
                name="sample_product_sampling_detail_line_uniq",
            ),
        ),
    ]
