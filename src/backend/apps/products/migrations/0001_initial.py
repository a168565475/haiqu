# Generated manually for the product information module.

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organizations", "0002_seed_root_organization"),
        ("reference_data", "0021_seed_accessory_data"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductInformation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("archive_reason", models.CharField(blank=True, max_length=500)),
                ("product_number", models.CharField(max_length=100, unique=True)),
                ("product_type", models.CharField(choices=[("FINISHED", "成品")], default="FINISHED", max_length=30)),
                ("product_code", models.CharField(blank=True, max_length=100)),
                ("product_name", models.CharField(max_length=200)),
                ("specification", models.CharField(max_length=300)),
                ("warehouse_number", models.CharField(blank=True, max_length=100)),
                ("warehouse_name", models.CharField(blank=True, max_length=150)),
                ("scale", models.CharField(choices=[("CUSTOM", "定制"), ("REGULAR", "常规")], max_length=20)),
                ("status", models.CharField(choices=[("ACTIVE", "正常"), ("INACTIVE", "废弃")], default="ACTIVE", max_length=20)),
                ("archived_by_employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="organizations.employee")),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="reference_data.productcategory")),
                ("product_item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="reference_data.productitem")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="products", to="reference_data.productionunit")),
            ],
            options={
                "db_table": "product_information",
                "ordering": ["product_number", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="productinformation",
            constraint=models.CheckConstraint(condition=models.Q(("product_type", "FINISHED")), name="product_information_type_finished"),
        ),
        migrations.AddConstraint(
            model_name="productinformation",
            constraint=models.CheckConstraint(condition=models.Q(("scale__in", ["CUSTOM", "REGULAR"])), name="product_information_scale_valid"),
        ),
        migrations.AddConstraint(
            model_name="productinformation",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["ACTIVE", "INACTIVE"])), name="product_information_status_valid"),
        ),
        migrations.AddConstraint(
            model_name="productinformation",
            constraint=models.UniqueConstraint(condition=models.Q(("product_code", ""), _negated=True), fields=("product_code",), name="product_information_code_uniq"),
        ),
        migrations.AddIndex(
            model_name="productinformation",
            index=models.Index(fields=["status", "category", "product_number"], name="prod_info_status_cat_idx"),
        ),
        migrations.AddIndex(
            model_name="productinformation",
            index=models.Index(fields=["scale", "product_number"], name="product_info_scale_idx"),
        ),
        migrations.AddIndex(
            model_name="productinformation",
            index=models.Index(fields=["-updated_at", "-id"], name="product_info_updated_idx"),
        ),
    ]
