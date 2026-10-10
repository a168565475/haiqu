# Generated manually for the raw material information module.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_seed_product_information"),
        ("reference_data", "0022_seed_raw_material_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="RawMaterialInformation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("material_number", models.CharField(db_index=True, max_length=100)),
                (
                    "item_type",
                    models.CharField(
                        choices=[("MATERIAL", "材料"), ("SEMI_FINISHED", "半成品")],
                        max_length=30,
                    ),
                ),
                ("material_name", models.CharField(max_length=200)),
                ("specification", models.CharField(max_length=300)),
                ("color_snapshot", models.CharField(blank=True, max_length=200)),
                ("material", models.CharField(blank=True, max_length=200)),
                ("is_packaging_auxiliary", models.BooleanField(default=False)),
                (
                    "box_shape",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("HALF_COVER", "半盖"),
                            ("FULL_COVER", "全盖"),
                            ("LID_AND_BASE", "天地盖"),
                            ("DISPLAY_BOX", "展示盒"),
                            ("OTHER", "其他"),
                        ],
                        max_length=30,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("warehouse_number", models.CharField(max_length=100)),
                ("warehouse_name", models.CharField(max_length=150)),
                ("diameter", models.CharField(blank=True, max_length=100)),
                ("length", models.CharField(blank=True, max_length=100)),
                ("width", models.CharField(blank=True, max_length=100)),
                ("thickness", models.CharField(blank=True, max_length=100)),
                ("model_number", models.CharField(blank=True, max_length=100)),
                ("weight_kg", models.CharField(blank=True, max_length=100)),
                ("flow_unit", models.CharField(blank=True, max_length=100)),
                ("number_value", models.CharField(blank=True, max_length=100)),
                ("source_unique_check", models.CharField(blank=True, max_length=300)),
                ("source_row_number", models.PositiveIntegerField(blank=True, null=True, unique=True)),
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
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="raw_materials",
                        to="reference_data.productcategory",
                    ),
                ),
                (
                    "color",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="raw_materials",
                        to="reference_data.productcolor",
                    ),
                ),
                (
                    "unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="raw_materials",
                        to="reference_data.productionunit",
                    ),
                ),
            ],
            options={
                "db_table": "raw_material_information",
                "ordering": ["material_number", "source_row_number", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="rawmaterialinformation",
            constraint=models.CheckConstraint(
                condition=models.Q(("item_type__in", ["MATERIAL", "SEMI_FINISHED"])),
                name="raw_material_item_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="rawmaterialinformation",
            constraint=models.CheckConstraint(
                condition=models.Q(("box_shape", ""))
                | models.Q(
                    ("box_shape__in", ["HALF_COVER", "FULL_COVER", "LID_AND_BASE", "DISPLAY_BOX", "OTHER"])
                ),
                name="raw_material_box_shape_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="rawmaterialinformation",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_row_number__isnull", True)),
                fields=("material_number",),
                name="raw_material_new_number_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="rawmaterialinformation",
            index=models.Index(
                fields=["item_type", "category", "material_number"],
                name="raw_material_type_cat_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="rawmaterialinformation",
            index=models.Index(
                fields=["warehouse_number", "warehouse_name"],
                name="raw_material_warehouse_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="rawmaterialinformation",
            index=models.Index(fields=["-updated_at", "-id"], name="raw_material_updated_idx"),
        ),
    ]
