from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("customers", "0004_seed_customer_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="customercontact",
            name="is_key_contact",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterModelOptions(
            name="customercontact",
            options={
                "permissions": [
                    ("import_customercontact", "可导入客户联系人"),
                    ("bulk_change_customercontact", "可批量变更客户联系人"),
                    ("bulk_create_contact_task", "可为联系人批量创建任务"),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="customercontactmethod",
            options={
                "permissions": [
                    ("view_sensitive_customercontactmethod", "可查看完整客户联系方式"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="customercontact",
            index=models.Index(
                fields=["customer_account", "status", "is_key_contact", "id"],
                condition=Q(archived_at__isnull=True),
                name="contact_account_status_idx",
            ),
        ),
    ]
