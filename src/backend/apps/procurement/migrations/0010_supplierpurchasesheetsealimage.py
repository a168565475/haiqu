import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0003_businessfile_scan_status_skipped"),
        ("organizations", "0001_initial"),
        ("procurement", "0009_purchaserequestallocation_supplier_purchase_sheet"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierPurchaseSheetSealImage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_supplier_purchase_sheet_seal_images",
                        to="organizations.employee",
                    ),
                ),
                (
                    "image_file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_purchase_sheet_seal_images",
                        to="files.businessfile",
                    ),
                ),
                (
                    "sheet",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="seal_image",
                        to="procurement.supplierpurchasesheet",
                    ),
                ),
            ],
            options={"db_table": "procurement_supplier_purchase_sheet_seal_image"},
        ),
    ]
