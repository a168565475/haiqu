import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("reference_data", "0028_fill_supplemental_accessory_units"),
    ]

    operations = [
        migrations.CreateModel(
            name="MaterialCatalog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("category_key", models.CharField(choices=[("TUBE", "管材"), ("FABRIC", "面料"), ("HARDWARE", "五金"), ("PLASTIC", "塑料件"), ("PACKAGING", "包材"), ("AUXILIARY", "辅料"), ("FABRIC_SEMI", "委外布面")], max_length=30)),
                ("template_key", models.CharField(choices=[("TUBE", "管材"), ("FABRIC", "面料"), ("HARDWARE", "五金"), ("PLASTIC", "塑料件"), ("CARTON", "纸箱"), ("BAG", "塑料袋"), ("TAPE", "带类"), ("COTTON", "棉类"), ("FABRIC_SEMI", "委外布面")], max_length=30)),
                ("name", models.CharField(max_length=200)),
                ("spray_enabled", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "material_catalog", "ordering": ["name", "id"],
                "default_permissions": ("add", "change", "view"),
                "constraints": [
                    models.UniqueConstraint(fields=("category_key", "name"), name="mat_catalog_category_name_uniq"),
                    models.CheckConstraint(condition=~models.Q(name=""), name="mat_catalog_name_not_empty"),
                    models.CheckConstraint(
                        condition=(models.Q(category_key="TUBE", template_key="TUBE")
                            | models.Q(category_key="FABRIC", template_key="FABRIC")
                            | models.Q(category_key="HARDWARE", template_key="HARDWARE")
                            | models.Q(category_key="PLASTIC", template_key="PLASTIC")
                            | models.Q(category_key="PACKAGING", template_key__in=["CARTON", "BAG"])
                            | models.Q(category_key="AUXILIARY", template_key__in=["TAPE", "COTTON"])
                            | models.Q(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")),
                        name="mat_catalog_template_valid",
                    ),
                    models.CheckConstraint(condition=models.Q(spray_enabled=False) | models.Q(category_key__in=["TUBE", "HARDWARE"]), name="mat_catalog_spray_valid"),
                ],
            },
        ),
        migrations.CreateModel(
            name="MaterialAttributeValue",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("scope", models.CharField(choices=[("BASE", "基础属性"), ("SPRAY", "喷塑属性")], max_length=10)),
                ("field_key", models.CharField(max_length=40)),
                ("value", models.CharField(max_length=300)),
                ("catalog", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attribute_values", to="material_catalog.materialcatalog")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="dimensions", to="material_catalog.materialattributevalue")),
            ],
            options={
                "db_table": "material_catalog_attribute_value", "ordering": ["created_at", "id"],
                "default_permissions": (),
                "constraints": [
                    models.UniqueConstraint(fields=("catalog", "scope", "field_key", "value", "parent"), nulls_distinct=False, name="mat_catalog_value_uniq"),
                    models.CheckConstraint(condition=models.Q(scope__in=["BASE", "SPRAY"]), name="mat_catalog_value_scope_valid"),
                    models.CheckConstraint(condition=~models.Q(value=""), name="mat_catalog_value_not_empty"),
                    models.CheckConstraint(
                        condition=(models.Q(field_key="section_size", scope="BASE", parent__isnull=False)
                            | (~models.Q(field_key="section_size") & models.Q(parent__isnull=True))),
                        name="mat_catalog_parent_shape_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MaterialAllowedUnit",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("scope", models.CharField(choices=[("BASE", "基础属性"), ("SPRAY", "喷塑属性")], max_length=10)),
                ("catalog", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="allowed_units", to="material_catalog.materialcatalog")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="material_catalog_options", to="reference_data.productionunit")),
            ],
            options={
                "db_table": "material_catalog_allowed_unit", "ordering": ["created_at", "id"],
                "default_permissions": (),
                "constraints": [
                    models.UniqueConstraint(fields=("catalog", "scope", "unit"), name="mat_catalog_unit_uniq"),
                    models.CheckConstraint(condition=models.Q(scope__in=["BASE", "SPRAY"]), name="mat_catalog_unit_scope_valid"),
                ],
            },
        ),
    ]
