import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("samples", "0025_material_purchase_source"),
    ]

    operations = [
        migrations.CreateModel(
            name="SampleParameterImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                (
                    "archive_reason",
                    models.CharField(blank=True, max_length=500),
                ),
                ("parameter_type", models.CharField(choices=[("METALWORK", "金工"), ("CUTTING", "裁剪")], max_length=20)),
                ("uploaded_at", models.DateTimeField()),
                (
                    "archived_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="organizations.employee",
                    ),
                ),
                (
                    "business_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sample_parameter_images",
                        to="files.businessfile",
                    ),
                ),
                (
                    "sample_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="parameter_images",
                        to="samples.samplerequest",
                    ),
                ),
                (
                    "uploaded_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_sample_parameter_images",
                        to="organizations.employee",
                    ),
                ),
            ],
            options={
                "db_table": "sample_parameter_image",
                "ordering": ["parameter_type", "uploaded_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["sample_request", "parameter_type", "archived_at", "uploaded_at"],
                        name="sample_param_image_active_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="sampleparameterimage",
            constraint=models.CheckConstraint(
                condition=models.Q(parameter_type__in=["METALWORK", "CUTTING"]),
                name="sample_parameter_image_type_valid",
            ),
        ),
    ]
