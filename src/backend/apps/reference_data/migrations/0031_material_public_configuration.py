import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0030_tube_calculation_formulas")]

    operations = [
        migrations.AlterField(model_name="productcolor", name="color_card", field=models.CharField(blank=True, max_length=100)),
        migrations.AlterField(model_name="productcolor", name="color_code", field=models.CharField(blank=True, max_length=100)),
        migrations.CreateModel(
            name="MaterialAttributePublicValue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("ACTIVE", "启用"), ("INACTIVE", "停用")], default="ACTIVE", max_length=20)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("category_key", models.CharField(max_length=30)),
                ("template_key", models.CharField(max_length=30)),
                ("scope", models.CharField(max_length=10)),
                ("field_key", models.CharField(max_length=40)),
                ("value", models.CharField(max_length=300)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
            ],
            options={
                "db_table": "reference_material_attribute_value", "ordering": ["sort_order", "value", "id"], "default_permissions": (),
                "constraints": [
                    models.UniqueConstraint(fields=("category_key", "template_key", "scope", "field_key", "value"), name="ref_material_attribute_unique"),
                    models.CheckConstraint(condition=models.Q(scope__in=["BASE", "SPRAY"]), name="ref_material_attribute_scope"),
                    models.CheckConstraint(condition=~models.Q(value=""), name="ref_material_attribute_nonempty"),
                    models.CheckConstraint(condition=models.Q(status__in=["ACTIVE", "INACTIVE"]), name="ref_material_attribute_status"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TubeShapeDimension",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("status", models.CharField(choices=[("ACTIVE", "启用"), ("INACTIVE", "停用")], default="ACTIVE", max_length=20)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("shape", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="size_options", to="reference_data.tubeshape")),
                ("diameter", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="shape_options", to="reference_data.tubediameter")),
            ],
            options={
                "db_table": "reference_tube_shape_dimension", "ordering": ["sort_order", "shape__shape_name", "diameter__diameter_value", "id"], "default_permissions": (),
                "constraints": [
                    models.UniqueConstraint(fields=("shape", "diameter"), name="ref_tube_shape_dimension_unique"),
                    models.CheckConstraint(condition=models.Q(status__in=["ACTIVE", "INACTIVE"]), name="ref_tube_shape_dimension_status"),
                ],
            },
        ),
    ]
