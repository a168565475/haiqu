from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("finance", "0010_purchase_payable_tax_freight")]

    operations = [
        migrations.AlterModelOptions(
            name="purchasepayable",
            options={
                "ordering": ["-created_at", "-id"],
                "default_permissions": ("add", "change", "delete", "view"),
                "permissions": [
                    ("confirm_purchasepayable", "确认采购应付"),
                    ("void_purchasepayable", "作废采购应付"),
                    ("view_supplierledger", "查看供应商往来明细"),
                ],
            },
        ),
    ]
